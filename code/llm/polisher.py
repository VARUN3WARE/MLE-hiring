"""Optional LLM response polisher with deterministic fallback."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from agent.issue_parser import combined_user_text, parse_issue
from agent.routing import RouteDecision
from llm.config import LLMConfig, load_llm_config
from llm.eligibility import LLMRowContext, is_llm_eligible
from llm.packet import build_polish_packet
from llm.prompts import SYSTEM_INSTRUCTION, build_user_message
from llm.provider import LLMProviderError, get_provider
from llm.validate import validate_llm_output
from retrieval.evidence import retrieve_evidence

_polish_calls_made = 0


@dataclass
class PolishStats:
    attempted: int = 0
    applied: int = 0
    skipped_ineligible: int = 0
    skipped_disabled: int = 0
    fallback_errors: list[str] = field(default_factory=list)


_STATS = PolishStats()


def get_polish_stats() -> PolishStats:
    return _STATS


def reset_polish_stats() -> None:
    from llm.config import reset_llm_config_cache

    global _polish_calls_made
    reset_llm_config_cache()
    _polish_calls_made = 0
    _STATS.attempted = 0
    _STATS.applied = 0
    _STATS.skipped_ineligible = 0
    _STATS.skipped_disabled = 0
    _STATS.fallback_errors.clear()


def _debug(msg: str, *, config: LLMConfig) -> None:
    if config.debug:
        sys.stderr.write(f"[llm] {msg}\n")


def maybe_polish_response(
    *,
    issue: str,
    subject: str,
    company: str,
    decision: RouteDecision,
    deterministic_response: str,
    config: LLMConfig | None = None,
) -> str:
    """
    Return LLM-polished response text when enabled, eligible, and validated.

    On any failure, returns deterministic_response unchanged (all other CSV fields
    remain the responsibility of the caller).
    """
    global _polish_calls_made

    cfg = config or load_llm_config()
    if not cfg.enabled:
        _STATS.skipped_disabled += 1
        return deterministic_response

    if cfg.provider != "openai":
        _record_fallback(cfg, "unsupported_provider")
        return deterministic_response

    if not cfg.api_key:
        _record_fallback(cfg, "missing_api_key")
        return deterministic_response

    if cfg.max_polish_calls is not None and _polish_calls_made >= cfg.max_polish_calls:
        _record_fallback(cfg, "max_polish_budget_exhausted")
        return deterministic_response

    parsed = parse_issue(issue)
    body = combined_user_text(parsed)
    ticket_text = "\n".join(p for p in (subject, body) if p)
    retrieval = retrieve_evidence(issue=issue, subject=subject, company=company)
    ctx = LLMRowContext(decision=decision, retrieval=retrieval, ticket_text=ticket_text)

    eligible, reasons = is_llm_eligible(ctx)
    if not eligible:
        _STATS.skipped_ineligible += 1
        _debug(f"ineligible: {reasons}", config=cfg)
        return deterministic_response

    packet = build_polish_packet(ctx)
    approved = frozenset(packet.approved_source_paths())
    if not approved:
        _record_fallback(cfg, "no_approved_sources")
        return deterministic_response

    _STATS.attempted += 1
    _polish_calls_made += 1

    try:
        provider = get_provider(cfg)
        raw = provider.complete_json(
            system=SYSTEM_INSTRUCTION,
            user=build_user_message(packet.to_dict()),
        )
    except LLMProviderError as exc:
        _record_fallback(cfg, str(exc))
        return deterministic_response
    except Exception as exc:  # noqa: BLE001 — never break CSV generation
        _record_fallback(cfg, f"unexpected:{type(exc).__name__}")
        return deterministic_response

    validated, errors = validate_llm_output(raw, approved_sources=approved)
    if validated is None:
        _record_fallback(cfg, f"validation:{';'.join(errors[:5])}")
        return deterministic_response

    _STATS.applied += 1
    _debug("applied polished response", config=cfg)
    return validated.response


def _record_fallback(config: LLMConfig, reason: str) -> None:
    _STATS.fallback_errors.append(reason)
    _debug(f"fallback: {reason}", config=config)
