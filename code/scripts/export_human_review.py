#!/usr/bin/env python3
"""
Export a curated Markdown sample for human supervision review.

Reads agent output CSVs (does not re-run or change the agent). Redacts PII in
exported ticket text. Aligns sampling buckets with submission/tests/human_supervision_review.md.

Usage (from repo root):
    python code/scripts/export_human_review.py
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CODE_DIR))

from agent.issue_parser import combined_user_text, parse_issue  # noqa: E402
from paths import REPO_ROOT  # noqa: E402
from safety.redaction import redact_text  # noqa: E402

DEFAULT_FIXTURES_DIR = REPO_ROOT / "code" / "tests" / "fixtures"
DEFAULT_SYNTHETIC_OUTPUT = DEFAULT_FIXTURES_DIR / "synthetic_output.csv"
DEFAULT_SYNTHETIC_METADATA = DEFAULT_FIXTURES_DIR / "expected_metadata.json"
DEFAULT_FUZZED_OUTPUT = DEFAULT_FIXTURES_DIR / "fuzzed_output.csv"
DEFAULT_FUZZED_METADATA = DEFAULT_FIXTURES_DIR / "fuzzed_metadata.json"
DEFAULT_OUT = DEFAULT_FIXTURES_DIR / "human_review_sample.md"

DEFAULT_SEED = 42
LOW_CONF_THRESHOLD = 0.6
HIGH_CONF_THRESHOLD = 0.85

DESTRUCTIVE_TOOLS = frozenset(
    {"verify_identity", "reset_password", "lock_account", "issue_refund", "modify_subscription"}
)

CATEGORY_TARGETS: tuple[tuple[str, int], ...] = (
    ("adversarial", 10),
    ("escalated", 10),
    ("replied", 10),
    ("llm_polished", 10),
    ("tool_action", 5),
    ("pii", 5),
    ("low_confidence", 5),
    ("high_confidence", 5),
)


@dataclass
class EnrichedRow:
    source_file: str
    row_index: int
    case_id: str
    issue: str
    subject: str
    company: str
    output: dict[str, str]
    meta: dict[str, Any] = field(default_factory=dict)
    sample_categories: list[str] = field(default_factory=list)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_metadata(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"Invalid metadata at {path}")
    return cases


def _parse_confidence(raw: str) -> float:
    try:
        return float((raw or "").strip())
    except ValueError:
        return 0.0


def _parse_actions(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text or text == "[]":
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _action_tool_names(actions: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in actions:
        if isinstance(item, dict):
            name = item.get("action") or item.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _is_pii_row(row: dict[str, str]) -> bool:
    return (row.get("pii_detected") or "").strip().lower() == "true"


def _is_adversarial(meta: dict[str, Any], row: dict[str, str]) -> bool:
    if meta.get("category") == "adversarial":
        return True
    tags = meta.get("tags") or []
    return "adversarial" in tags


def _has_meaningful_tool_action(actions: list[dict[str, Any]]) -> bool:
    names = _action_tool_names(actions)
    if not names:
        return False
    return any(n in DESTRUCTIVE_TOOLS for n in names) or len(names) > 0


def _format_issue_for_review(issue_raw: str, *, max_chars: int = 2400) -> str:
    parsed = parse_issue(issue_raw)
    if parsed.parse_error:
        collapsed = redact_text(parsed.raw or issue_raw)
        text = f"(parse note: {parsed.parse_error})\n{collapsed}"
    else:
        lines: list[str] = []
        for msg in parsed.messages:
            role = (msg.get("role") or "user").strip().lower()
            content = redact_text(msg.get("content") or "")
            lines.append(f"**{role}**: {content}")
        text = "\n\n".join(lines) if lines else redact_text(issue_raw)
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def _format_response_for_review(response: str, *, max_chars: int = 2000) -> str:
    text = redact_text(response or "").strip()
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def _format_sources(raw: str) -> str:
    if not (raw or "").strip():
        return "_none_"
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if len(parts) <= 5:
        return "\n".join(f"- `{p}`" for p in parts)
    head = "\n".join(f"- `{p}`" for p in parts[:5])
    return f"{head}\n- _… and {len(parts) - 5} more_"


def _format_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "_none_"
    return "```json\n" + json.dumps(actions, indent=2, ensure_ascii=False) + "\n```"


def _load_dataset(
    *,
    output_path: Path,
    metadata_path: Path | None,
    source_label: str,
) -> list[EnrichedRow]:
    if not output_path.is_file():
        return []

    outputs = _read_csv(output_path)
    meta_cases: list[dict[str, Any]] = []
    if metadata_path and metadata_path.is_file():
        meta_cases = _load_metadata(metadata_path)
        if len(meta_cases) != len(outputs):
            raise ValueError(
                f"Row count mismatch for {output_path.name}: "
                f"{len(outputs)} output vs {len(meta_cases)} metadata"
            )

    enriched: list[EnrichedRow] = []
    for index, out_row in enumerate(outputs, start=1):
        meta = meta_cases[index - 1] if meta_cases else {}
        case_id = str(meta.get("case_id") or f"{source_label}-row-{index}")
        enriched.append(
            EnrichedRow(
                source_file=source_label,
                row_index=index,
                case_id=case_id,
                issue=out_row.get("issue") or "",
                subject=out_row.get("subject") or "",
                company=out_row.get("company") or "",
                output=out_row,
                meta=meta,
            )
        )
    return enriched


def _sample(
    pool: list[EnrichedRow],
    rng: random.Random,
    n: int,
    *,
    predicate: Callable[[EnrichedRow], bool],
) -> list[EnrichedRow]:
    candidates = [row for row in pool if predicate(row)]
    rng.shuffle(candidates)
    return candidates[:n]


def _collect_samples(pool: list[EnrichedRow], *, seed: int) -> dict[str, list[EnrichedRow]]:
    rng = random.Random(seed)
    buckets: dict[str, list[EnrichedRow]] = {}

    buckets["adversarial"] = _sample(
        pool,
        rng,
        10,
        predicate=lambda r: _is_adversarial(r.meta, r.output),
    )

    buckets["escalated"] = _sample(
        pool,
        rng,
        10,
        predicate=lambda r: (r.output.get("status") or "").lower() == "escalated",
    )

    buckets["replied"] = _sample(
        pool,
        rng,
        10,
        predicate=lambda r: (r.output.get("status") or "").lower() == "replied",
    )

    # LLM polish is not persisted in CSV; optional sidecar may be added later.
    llm_polished: list[EnrichedRow] = []
    for row in pool:
        if row.meta.get("llm_polished") is True or row.output.get("llm_polished", "").lower() == "true":
            llm_polished.append(row)
    rng.shuffle(llm_polished)
    buckets["llm_polished"] = llm_polished[:10]

    def _tool_priority(row: EnrichedRow) -> tuple[int, float]:
        names = _action_tool_names(_parse_actions(row.output.get("actions_taken") or ""))
        has_destructive = any(n in DESTRUCTIVE_TOOLS for n in names)
        return (0 if has_destructive else 1, _parse_confidence(row.output.get("confidence_score", "")))

    tool_candidates = [r for r in pool if _has_meaningful_tool_action(_parse_actions(r.output.get("actions_taken") or ""))]
    tool_candidates.sort(key=_tool_priority)
    rng.shuffle(tool_candidates[: max(20, len(tool_candidates))])
    destructive_first = sorted(tool_candidates, key=_tool_priority)
    buckets["tool_action"] = destructive_first[:5]

    buckets["pii"] = _sample(pool, rng, 5, predicate=lambda r: _is_pii_row(r.output))

    low_pool = sorted(
        [r for r in pool if _parse_confidence(r.output.get("confidence_score", "")) <= LOW_CONF_THRESHOLD],
        key=lambda r: _parse_confidence(r.output.get("confidence_score", "")),
    )
    buckets["low_confidence"] = low_pool[:5]

    high_pool = sorted(
        [r for r in pool if _parse_confidence(r.output.get("confidence_score", "")) > HIGH_CONF_THRESHOLD],
        key=lambda r: _parse_confidence(r.output.get("confidence_score", "")),
        reverse=True,
    )
    if len(high_pool) < 5:
        # No rows above threshold — take the five highest scores available.
        high_pool = sorted(
            pool,
            key=lambda r: _parse_confidence(r.output.get("confidence_score", "")),
            reverse=True,
        )[:5]
    buckets["high_confidence"] = high_pool[:5]

    return buckets


def _assign_categories(buckets: dict[str, list[EnrichedRow]]) -> list[EnrichedRow]:
    """Merge buckets into export list, tagging each row with its sample category."""
    ordered: list[EnrichedRow] = []
    seen: set[tuple[str, int, str]] = set()

    for category, _target in CATEGORY_TARGETS:
        for row in buckets.get(category, []):
            key = (row.source_file, row.row_index, category)
            if key in seen:
                continue
            seen.add(key)
            export_row = EnrichedRow(
                source_file=row.source_file,
                row_index=row.row_index,
                case_id=row.case_id,
                issue=row.issue,
                subject=row.subject,
                company=row.company,
                output=row.output,
                meta=row.meta,
                sample_categories=[category],
            )
            ordered.append(export_row)
    return ordered


def _render_review_block(row: EnrichedRow) -> str:
    out = row.output
    category = row.sample_categories[0] if row.sample_categories else "sample"
    actions = _parse_actions(out.get("actions_taken") or "")
    conf = out.get("confidence_score", "")
    llm_note = (out.get("llm_polished") or row.meta.get("llm_polished") or "unknown")

    lines = [
        f"## [{category}] {row.case_id}",
        "",
        f"- **Source:** `{row.source_file}` row {row.row_index}",
        f"- **Subject:** {redact_text(row.subject)}",
        f"- **Company:** {row.company or '—'}",
        f"- **Status:** `{out.get('status', '')}`",
        f"- **Request type:** `{out.get('request_type', '')}`",
        f"- **Risk level:** `{out.get('risk_level', '')}`",
        f"- **PII detected (agent):** `{out.get('pii_detected', '')}`",
        f"- **Confidence score:** `{conf}`",
        f"- **LLM polished:** `{llm_note}`",
        "",
        "### Issue (redacted)",
        "",
        _format_issue_for_review(row.issue),
        "",
        "### Response",
        "",
        _format_response_for_review(out.get("response") or ""),
        "",
        "### Actions taken",
        "",
        _format_actions(actions),
        "",
        "### Cited sources",
        "",
        _format_sources(out.get("source_documents") or ""),
        "",
        "### Justification",
        "",
        redact_text((out.get("justification") or "").strip()) or "_none_",
        "",
        "### Human review scores (1–5)",
        "",
        "| Dimension | Score (1–5) | Notes |",
        "|-----------|-------------|-------|",
        "| Safety | | |",
        "| Grounding | | |",
        "| Escalation judgment | | |",
        "| Helpfulness | | |",
        "| Confidence calibration | | |",
        "",
        "**Human label:** `approved` / `needs_wording_fix` / `needs_routing_fix` / "
        "`needs_retrieval_fix` / `needs_safety_fix` / `needs_confidence_fix` / `blocker`",
        "",
        "**Reviewer notes:**",
        "",
        "_What is good:_",
        "",
        "_What needs fix:_",
        "",
        "_Recommended change:_",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def build_markdown(
    buckets: dict[str, list[EnrichedRow]],
    *,
    sources: list[str],
    seed: int,
) -> str:
    counts = {name: len(buckets.get(name, [])) for name, _ in CATEGORY_TARGETS}
    total_unique = len(_assign_categories(buckets))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    header = [
        "# Human Supervision Review Sample",
        "",
        f"_Generated: {generated}_",
        "",
        "Curated export for vibe-checking tone, grounding, escalation judgment, and "
        "confidence calibration. Ticket text is redacted; agent outputs are read-only.",
        "",
        f"- **Seed:** {seed}",
        f"- **Sources:** {', '.join(f'`{s}`' for s in sources)}",
        f"- **Unique review blocks:** {total_unique}",
        "",
        "## Sample counts by category",
        "",
        "| Category | Target | Exported |",
        "|----------|--------|----------|",
    ]
    for name, target in CATEGORY_TARGETS:
        exported = counts.get(name, 0)
        note = ""
        if name == "llm_polished" and exported == 0:
            note = " _(skipped — no LLM-polished rows in source CSV)_"
        if name == "high_confidence" and exported > 0:
            max_conf = max(
                (
                    _parse_confidence(r.output.get("confidence_score", ""))
                    for r in buckets.get("high_confidence", [])
                ),
                default=0.0,
            )
            if max_conf <= HIGH_CONF_THRESHOLD:
                note = f" _(top scores; none > {HIGH_CONF_THRESHOLD}; max={max_conf:.2f})_"
        header.append(f"| {name} | {target} | {exported}{note} |")

    header.extend(
        [
            "",
            "See `submission/tests/human_supervision_review.md` for the full rubric.",
            "",
            "---",
            "",
        ]
    )

    body_parts = [_render_review_block(row) for row in _assign_categories(buckets)]
    return "\n".join(header) + "\n".join(body_parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export human supervision review Markdown sample")
    parser.add_argument("--synthetic-output", type=Path, default=DEFAULT_SYNTHETIC_OUTPUT)
    parser.add_argument("--synthetic-metadata", type=Path, default=DEFAULT_SYNTHETIC_METADATA)
    parser.add_argument("--fuzzed-output", type=Path, default=DEFAULT_FUZZED_OUTPUT)
    parser.add_argument("--fuzzed-metadata", type=Path, default=DEFAULT_FUZZED_METADATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--include-fuzzed", action="store_true", default=True)
    parser.add_argument("--no-fuzzed", action="store_false", dest="include_fuzzed")
    args = parser.parse_args(argv)

    pool: list[EnrichedRow] = []
    sources: list[str] = []

    if args.synthetic_output.is_file():
        pool.extend(
            _load_dataset(
                output_path=args.synthetic_output,
                metadata_path=args.synthetic_metadata if args.synthetic_metadata.is_file() else None,
                source_label=args.synthetic_output.name,
            )
        )
        sources.append(str(args.synthetic_output.relative_to(REPO_ROOT)))

    if args.include_fuzzed and args.fuzzed_output.is_file():
        pool.extend(
            _load_dataset(
                output_path=args.fuzzed_output,
                metadata_path=args.fuzzed_metadata if args.fuzzed_metadata.is_file() else None,
                source_label=args.fuzzed_output.name,
            )
        )
        sources.append(str(args.fuzzed_output.relative_to(REPO_ROOT)))

    if not pool:
        print("Error: no output CSV found to sample.", file=sys.stderr)
        return 1

    buckets = _collect_samples(pool, seed=args.seed)
    markdown = build_markdown(buckets, sources=sources, seed=args.seed)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")

    print(f"Wrote {args.output}")
    print("Sample counts:")
    for name, target in CATEGORY_TARGETS:
        exported = len(buckets.get(name, []))
        print(f"  {name}: {exported}/{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
