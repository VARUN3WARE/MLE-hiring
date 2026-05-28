"""Build deterministic LLM polish packets (no API calls).

Packets include locked routing decisions, redacted ticket text, the deterministic
draft response, and approved evidence snippets only. Source path lists are sorted
for stable serialization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.routing import RouteDecision
from llm.eligibility import LLMRowContext
from paths import REPO_ROOT
from retrieval.evidence import RetrievalResult
from safety.redaction import redact_text
from schemas.ticket_categories import is_hub_path

POLISH_TASK = "Polish the response only. Preserve all factual meaning."

MAX_TICKET_SUMMARY_LEN = 400
MAX_EVIDENCE_SNIPPETS = 3

# Mirrors submission/set 2/llm_prompt_contract.md — descriptive only in the packet.
OUTPUT_FIELD_SCHEMA: dict[str, str] = {
    "response": "string",
    "used_sources": ["string"],
    "changed_meaning": "boolean",
    "pii_echo_risk": "boolean",
}


@dataclass(frozen=True)
class ApprovedEvidence:
    source: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "snippet": self.snippet}


@dataclass(frozen=True)
class LLMPolishPacket:
    task: str
    decision_locked: dict[str, Any]
    redacted_ticket_summary: str
    deterministic_response: str
    approved_evidence: tuple[ApprovedEvidence, ...]
    output_schema: dict[str, str]

    def approved_source_paths(self) -> tuple[str, ...]:
        locked = self.decision_locked.get("source_documents")
        if not isinstance(locked, list):
            return ()
        return tuple(str(p) for p in locked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "decision_locked": self.decision_locked,
            "redacted_ticket_summary": self.redacted_ticket_summary,
            "deterministic_response": self.deterministic_response,
            "approved_evidence": [item.to_dict() for item in self.approved_evidence],
            "output_schema": dict(self.output_schema),
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def approved_source_paths(decision: RouteDecision, retrieval: RetrievalResult) -> tuple[str, ...]:
    """
    Deterministic approved corpus paths for LLM packets.

    Uses the pipe-separated paths already chosen by the deterministic pipeline,
    keeping only paths that exist on disk and appear in retrieval hits (when any).
    Hub index pages are excluded when at least one non-hub article is present
    (matches compose_reply source selection).
    """
    from_paths: list[str] = []
    if decision.source_documents:
        for part in decision.source_documents.split("|"):
            part = part.strip()
            if part and (REPO_ROOT / part).is_file():
                from_paths.append(part)

    if not from_paths and retrieval.items:
        for item in retrieval.items:
            if (REPO_ROOT / item.path).is_file():
                from_paths.append(item.path)

    articles = [p for p in from_paths if not is_hub_path(p)]
    if articles:
        chosen = articles
    else:
        chosen = list(from_paths)

    seen: set[str] = set()
    ordered: list[str] = []
    for path in sorted(chosen):
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


def approved_evidence_for_paths(
    retrieval: RetrievalResult,
    paths: tuple[str, ...],
    *,
    max_items: int = MAX_EVIDENCE_SNIPPETS,
) -> tuple[ApprovedEvidence, ...]:
    """One snippet per approved path, in path sort order."""
    by_path: dict[str, str] = {}
    for item in retrieval.items:
        if item.path not in paths or item.path in by_path:
            continue
        snippet = (item.snippet or "").strip()
        if snippet:
            by_path[item.path] = snippet

    items: list[ApprovedEvidence] = []
    for path in paths:
        if path not in by_path:
            continue
        items.append(ApprovedEvidence(source=path, snippet=by_path[path]))
        if len(items) >= max_items:
            break
    return tuple(items)


def redacted_ticket_summary(ticket_text: str, *, max_len: int = MAX_TICKET_SUMMARY_LEN) -> str:
    """Single-line redacted summary; never includes raw PII spans."""
    collapsed = " ".join(redact_text(ticket_text or "").split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 3] + "..."


def build_locked_decision(decision: RouteDecision, source_paths: tuple[str, ...]) -> dict[str, Any]:
    """Routing fields the LLM must not change."""
    return {
        "status": decision.status,
        "request_type": decision.request_type,
        "risk_level": decision.risk_level,
        "product_area": decision.product_area,
        "source_documents": list(source_paths),
        "actions_taken": list(decision.actions),
    }


def build_polish_packet(ctx: LLMRowContext) -> LLMPolishPacket:
    """
    Construct a polish packet from deterministic pipeline outputs.

    Caller should gate with is_llm_eligible() before sending to an LLM.
    """
    decision = ctx.decision
    paths = approved_source_paths(decision, ctx.retrieval)
    evidence = approved_evidence_for_paths(ctx.retrieval, paths)
    return LLMPolishPacket(
        task=POLISH_TASK,
        decision_locked=build_locked_decision(decision, paths),
        redacted_ticket_summary=redacted_ticket_summary(ctx.ticket_text),
        deterministic_response=decision.response,
        approved_evidence=evidence,
        output_schema=dict(OUTPUT_FIELD_SCHEMA),
    )
