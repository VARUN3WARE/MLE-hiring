#!/usr/bin/env python3
"""Unit tests for gated LLM eligibility (no API calls, no routing changes)."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.issue_parser import combined_user_text, parse_issue  # noqa: E402
from agent.routing import RouteDecision, route_ticket  # noqa: E402
from llm.eligibility import LLMRowContext, is_llm_eligible  # noqa: E402
from retrieval.evidence import retrieve_evidence  # noqa: E402
from safety import classify_ticket  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SYNTHETIC_TICKETS = FIXTURES_DIR / "synthetic_tickets.csv"
SYNTHETIC_METADATA = FIXTURES_DIR / "expected_metadata.json"
VISIBLE_CSV = Path(__file__).resolve().parents[2] / "support_tickets" / "support_tickets.csv"


def _load_synthetic_cases() -> list[tuple[dict[str, Any], dict[str, str]]]:
    meta = json.loads(SYNTHETIC_METADATA.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(SYNTHETIC_TICKETS.open(newline="", encoding="utf-8")))
    cases = meta["cases"]
    if len(cases) != len(rows):
        raise ValueError("synthetic tickets/metadata length mismatch")
    return list(zip(cases, rows))


def _row_context(row: dict[str, str]) -> LLMRowContext:
    issue = row.get("Issue") or row.get("issue") or ""
    subject = row.get("Subject") or row.get("subject") or ""
    company = row.get("Company") or row.get("company") or ""
    parsed = parse_issue(issue)
    body = combined_user_text(parsed)
    ticket_text = "\n".join(p for p in (subject, body) if p)
    decision = route_ticket(issue=issue, subject=subject, company=company)
    retrieval = retrieve_evidence(issue=issue, subject=subject, company=company)
    return LLMRowContext(decision=decision, retrieval=retrieval, ticket_text=ticket_text)


def _case_by_id(case_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    for case, row in _load_synthetic_cases():
        if case.get("case_id") == case_id:
            return case, row
    raise KeyError(f"unknown synthetic case_id: {case_id}")


def _assert_blocked(ctx: LLMRowContext, *expected_reason_substrings: str) -> None:
    eligible, reasons = is_llm_eligible(ctx)
    assert not eligible, f"expected blocked, got eligible with reasons={reasons}"
    joined = " ".join(reasons)
    for fragment in expected_reason_substrings:
        assert any(fragment in r for r in reasons) or fragment in joined, (
            f"expected block reason containing {fragment!r}, got {reasons}"
        )


def _fake_ctx(
    *,
    status: str = "replied",
    request_type: str = "product_issue",
    risk_level: str = "low",
    source_documents: str = "data/claude/claude/get-started-with-claude/8114491-get-started-with-claude.md",
    is_adversarial: bool = False,
    pii_detected: bool = False,
    risk_signals: tuple[str, ...] = (),
    overall_grade: str = "strong",
    ticket_text: str = "How do I get started?",
    actions: list | None = None,
) -> LLMRowContext:
    from retrieval.evidence import EvidenceItem, RetrievalResult
    from retrieval.query import RetrievalQuery

    assessment = classify_ticket(ticket_text)

    decision = RouteDecision(
        status=status,
        request_type=request_type,
        risk_level=risk_level,
        product_area="general",
        response="Deterministic draft.",
        justification="test",
        confidence_score="0.50",
        source_documents=source_documents,
        actions=actions or [],
        assessment=assessment,
    )
    path = source_documents.split("|")[0].strip() if source_documents else ""
    item = EvidenceItem(
        path=path or "data/claude/claude/get-started-with-claude/8114491-get-started-with-claude.md",
        title="t",
        score=9.0,
        snippet="snippet",
        domain_hints=("claude",),
        chunk_id="c0",
    )
    query = RetrievalQuery(
        text="faq",
        tokens=("faq",),
        company_domain="claude",
        text_domain_scores=(("claude", 1),),
        intent_terms=(),
    )
    retrieval = RetrievalResult(
        query=query,
        items=(item,),
        overall_grade=overall_grade,
        notes=(),
    )
    return LLMRowContext(decision=decision, retrieval=retrieval, ticket_text=ticket_text)


def test_adversarial_tickets_blocked() -> None:
    for case_id in ("adv-authority-01", "adv-override-01", "adv-exfil-02"):
        _, row = _case_by_id(case_id)
        _assert_blocked(_row_context(row), "adversarial")


def test_pii_tickets_blocked() -> None:
    for case_id in ("pii-01", "pii-06", "pii-15"):
        _, row = _case_by_id(case_id)
        _assert_blocked(_row_context(row), "pii")


def test_high_risk_and_escalation_blocked() -> None:
    for case_id in ("esc-legal-03", "esc-refund-missing-id-02", "esc-takeover-01"):
        _, row = _case_by_id(case_id)
        ctx = _row_context(row)
        _assert_blocked(ctx, "status_not_replied")


def test_weak_evidence_blocked() -> None:
    _, row = _case_by_id("src-weak-evidence-01")
    ctx = _row_context(row)
    _assert_blocked(ctx, "status_not_replied")


def test_destructive_account_action_blocked() -> None:
    _, row = _case_by_id("esc-subscription-01")
    _assert_blocked(_row_context(row), "status_not_replied")


def test_multilingual_blocked() -> None:
    _, row = _case_by_id("resp-multilingual-01")
    _assert_blocked(_row_context(row), "multilingual")


def test_synthetic_eligibility_matrix() -> None:
    """llm_allowed fixtures must be eligible when the deterministic pipeline produces a strong reply."""
    for case, row in _load_synthetic_cases():
        ctx = _row_context(row)
        eligible, reasons = is_llm_eligible(ctx)
        if case.get("category") == "adversarial":
            assert not eligible, f"{case['case_id']}: adversarial fixture must be blocked: {reasons}"
            continue
        if not case.get("llm_allowed"):
            continue
        if (
            ctx.decision.status == "replied"
            and ctx.retrieval.overall_grade == "strong"
            and ctx.decision.source_documents
            and not ctx.decision.actions
        ):
            assert eligible, f"{case['case_id']}: expected eligible, blocked by {reasons}"


def test_safe_faq_eligible() -> None:
    _, row = _case_by_id("resp-faq-01")
    eligible, reasons = is_llm_eligible(_row_context(row))
    assert eligible, f"resp-faq-01 should be eligible: {reasons}"


def test_manual_blocks_from_fake_context() -> None:
    _assert_blocked(_fake_ctx(status="escalated"), "status_not_replied")
    _assert_blocked(_fake_ctx(request_type="invalid"), "request_type_invalid")
    _assert_blocked(_fake_ctx(overall_grade="weak"), "evidence_not_strong")
    _assert_blocked(_fake_ctx(source_documents=""), "missing_source_documents")
    _assert_blocked(
        _fake_ctx(actions=[{"action": "verify_identity", "parameters": {"method": "email_otp", "target": "x@y.com"}}]),
        "has_actions_taken",
    )
    _assert_blocked(
        _fake_ctx(ticket_text="Cancel my subscription immediately without verification."),
        "account_action",
    )


def test_eligible_fake_context() -> None:
    ctx = _fake_ctx()
    eligible, reasons = is_llm_eligible(ctx)
    assert eligible, reasons


def audit_visible_tickets() -> None:
    """Optional diagnostic over visible challenge CSV (no row numbers in assertions)."""
    with VISIBLE_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    counts = Counter()
    eligible_total = 0
    for row in rows:
        issue = row.get("Issue") or row.get("issue") or ""
        subject = row.get("Subject") or row.get("subject") or ""
        company = row.get("Company") or row.get("company") or ""
        parsed = parse_issue(issue)
        body = combined_user_text(parsed)
        ticket_text = "\n".join(p for p in (subject, body) if p)
        decision = route_ticket(issue=issue, subject=subject, company=company)
        retrieval = retrieve_evidence(issue=issue, subject=subject, company=company)
        ctx = LLMRowContext(decision=decision, retrieval=retrieval, ticket_text=ticket_text)
        eligible, reasons = is_llm_eligible(ctx)
        eligible_total += int(eligible)
        for r in reasons:
            counts[r] += 1
    print(f"Visible set: {eligible_total}/{len(rows)} eligible for LLM polish")
    for reason, n in counts.most_common(8):
        print(f"  {reason}: {n}")


def main() -> int:
    tests = [
        test_adversarial_tickets_blocked,
        test_pii_tickets_blocked,
        test_high_risk_and_escalation_blocked,
        test_weak_evidence_blocked,
        test_destructive_account_action_blocked,
        test_multilingual_blocked,
        test_synthetic_eligibility_matrix,
        test_safe_faq_eligible,
        test_manual_blocks_from_fake_context,
        test_eligible_fake_context,
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
    if "--audit-visible" in sys.argv:
        print()
        audit_visible_tickets()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
