#!/usr/bin/env python3
"""Unit tests for LLM polish packet construction and output schema validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.routing import RouteDecision  # noqa: E402
from llm.eligibility import LLMRowContext  # noqa: E402
from llm.packet import (  # noqa: E402
    LLMPolishPacket,
    OUTPUT_FIELD_SCHEMA,
    approved_evidence_for_paths,
    approved_source_paths,
    build_polish_packet,
    redacted_ticket_summary,
)
from llm.validate import validate_llm_output  # noqa: E402
from retrieval.evidence import EvidenceItem, RetrievalResult  # noqa: E402
from safety import classify_ticket  # noqa: E402


def _fake_decision(
    *,
    source_documents: str = "data/claude/claude/get-started-with-claude/8114491-get-started-with-claude.md",
    response: str = "Deterministic draft about getting started.",
) -> RouteDecision:
    assessment = classify_ticket("How do I get started with Claude?")
    return RouteDecision(
        status="replied",
        request_type="product_issue",
        risk_level="low",
        product_area="claude_general",
        response=response,
        justification="test",
        confidence_score="0.72",
        source_documents=source_documents,
        actions=[],
        assessment=assessment,
    )


def _fake_retrieval(path: str, snippet: str) -> RetrievalResult:
    item = EvidenceItem(
        path=path,
        title="Getting started",
        score=9.0,
        snippet=snippet,
        domain_hints=("claude",),
        chunk_id="c0",
    )
    from retrieval.query import RetrievalQuery

    query = RetrievalQuery(
        text="claude get started",
        tokens=("claude", "started"),
        company_domain="claude",
        text_domain_scores=(("claude", 2),),
        intent_terms=("started",),
    )
    return RetrievalResult(
        query=query,
        items=(item,),
        overall_grade="strong",
        notes=(),
    )


def test_packet_shape_and_locked_fields() -> None:
    path = "data/claude/claude/get-started-with-claude/8114491-get-started-with-claude.md"
    decision = _fake_decision(source_documents=path)
    retrieval = _fake_retrieval(path, "Claude is a helpful assistant.")
    ctx = LLMRowContext(
        decision=decision,
        retrieval=retrieval,
        ticket_text="How do I get started with Claude?",
    )
    packet = build_polish_packet(ctx)
    data = packet.to_dict()

    required_top = {
        "task",
        "decision_locked",
        "redacted_ticket_summary",
        "deterministic_response",
        "approved_evidence",
        "output_schema",
    }
    assert required_top <= set(data.keys()), f"unexpected top-level keys: {set(data) - required_top}"
    assert len(data) == len(required_top)

    locked = data["decision_locked"]
    for key in (
        "status",
        "request_type",
        "risk_level",
        "product_area",
        "source_documents",
        "actions_taken",
    ):
        assert key in locked, f"missing locked field {key}"
    assert "confidence_score" not in locked
    assert locked["status"] == "replied"
    assert locked["source_documents"] == [path]
    assert data["deterministic_response"] == decision.response
    assert data["output_schema"] == OUTPUT_FIELD_SCHEMA
    assert len(data["approved_evidence"]) == 1
    assert data["approved_evidence"][0]["source"] == path


def test_redacted_summary_strips_pii() -> None:
    raw = "Please call me at 555-123-4567 or email me at user@example.com"
    summary = redacted_ticket_summary(raw)
    assert "555-123-4567" not in summary
    assert "user@example.com" not in summary
    assert "[REDACTED" in summary


def test_approved_paths_deterministic_and_evidence_subset() -> None:
    path_a = "data/claude/claude/get-started-with-claude/8114491-get-started-with-claude.md"
    path_b = "data/claude/index.md"
    decision = _fake_decision(source_documents=f"{path_b}|{path_a}")
    retrieval = RetrievalResult(
        query=_fake_retrieval(path_a, "snippet a").query,
        items=(
            EvidenceItem(path_a, "a", 9.0, "Snippet A", ("claude",), "a0"),
            EvidenceItem(path_b, "hub", 8.0, "Hub snippet", ("claude",), "b0"),
        ),
        overall_grade="strong",
        notes=(),
    )
    paths = approved_source_paths(decision, retrieval)
    assert paths == (path_a,), "hub should drop when a non-hub article is approved"
    evidence = approved_evidence_for_paths(retrieval, paths)
    assert {e.source for e in evidence} <= set(paths)


def test_validate_accepts_well_formed_output() -> None:
    path = "data/claude/claude/get-started-with-claude/8114491-get-started-with-claude.md"
    approved = frozenset({path})
    payload = {
        "response": "Here is a polished getting-started answer.",
        "used_sources": [path],
        "changed_meaning": False,
        "pii_echo_risk": False,
    }
    result, errors = validate_llm_output(payload, approved_sources=approved)
    assert errors == [], errors
    assert result is not None
    assert result.used_sources == (path,)


def test_validate_rejects_extra_fields() -> None:
    path = "data/example/path.md"
    approved = frozenset({path})
    payload = {
        "response": "Polished text.",
        "used_sources": [],
        "changed_meaning": False,
        "pii_echo_risk": False,
        "status": "escalated",
    }
    _, errors = validate_llm_output(payload, approved_sources=approved)
    assert any(e.startswith("extra_key:") for e in errors)


def test_validate_rejects_unapproved_used_sources() -> None:
    approved = frozenset({"data/approved/a.md"})
    payload = {
        "response": "Polished.",
        "used_sources": ["data/unapproved/b.md"],
        "changed_meaning": False,
        "pii_echo_risk": False,
    }
    _, errors = validate_llm_output(payload, approved_sources=approved)
    assert any("unapproved_source:" in e for e in errors)


def test_validate_rejects_unapproved_path_in_response_body() -> None:
    approved = frozenset({"data/approved/a.md"})
    payload = {
        "response": "See data/unapproved/b.md for details.",
        "used_sources": [],
        "changed_meaning": False,
        "pii_echo_risk": False,
    }
    _, errors = validate_llm_output(payload, approved_sources=approved)
    assert any(e.startswith("unapproved_path_in_response:") for e in errors)


def test_validate_rejects_safety_flags_and_invalid_json() -> None:
    approved = frozenset()
    for bad_flag in ("changed_meaning", "pii_echo_risk"):
        payload = {
            "response": "x",
            "used_sources": [],
            bad_flag: True,
            "changed_meaning": False,
            "pii_echo_risk": False,
        }
        payload[bad_flag] = True
        _, errors = validate_llm_output(payload, approved_sources=approved)
        assert f"{bad_flag}_true" in errors

    _, errors = validate_llm_output("not json", approved_sources=approved)
    assert any(e.startswith("invalid_json:") for e in errors)


def test_packet_json_roundtrip() -> None:
    decision = _fake_decision()
    path = decision.source_documents
    retrieval = _fake_retrieval(path, "snippet")
    packet: LLMPolishPacket = build_polish_packet(
        LLMRowContext(decision=decision, retrieval=retrieval, ticket_text="FAQ question")
    )
    roundtrip = json.loads(packet.to_json())
    assert roundtrip["decision_locked"]["source_documents"] == list(packet.approved_source_paths())


def main() -> int:
    tests = [
        test_packet_shape_and_locked_fields,
        test_redacted_summary_strips_pii,
        test_approved_paths_deterministic_and_evidence_subset,
        test_validate_accepts_well_formed_output,
        test_validate_rejects_extra_fields,
        test_validate_rejects_unapproved_used_sources,
        test_validate_rejects_unapproved_path_in_response_body,
        test_validate_rejects_safety_flags_and_invalid_json,
        test_packet_json_roundtrip,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as exc:  # noqa: BLE001 — test runner
            failures.append(f"{test.__name__}: {exc}")
            print(f"FAIL: {test.__name__}: {exc}")

    if failures:
        print(f"\n{len(failures)} test(s) failed.")
        return 1
    print(f"\nAll {len(tests)} test(s) passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
