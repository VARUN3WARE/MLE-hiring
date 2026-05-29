#!/usr/bin/env python3
"""
Deterministic baseline scaffold for the MLE Hiring Challenge.

Reads support_tickets/support_tickets.csv and writes support_tickets/output.csv
with structurally valid decisions. Optional LLM polishing is env-gated (see .env.example).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap
from pathlib import Path

from agent.baseline import build_baseline_row
from llm.config import load_llm_config
from llm.polisher import get_polish_stats, reset_polish_stats
from paths import DEFAULT_INPUT_CSV, DEFAULT_OUTPUT_CSV, OUTPUT_COLUMNS

_INTERACTIVE_BANNER = """
Interactive mode — run one ticket at a time (live red-teaming).
Commands: blank line after issue JSON to finish paste; 'quit' or 'exit' to leave.
""".strip()


def process_tickets(input_path: Path, output_path: Path) -> tuple[int, int]:
    """
    Read input CSV, emit output CSV. Returns (rows_read, rows_written).

    Row-level failures are logged to stderr; processing continues.
    """
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    rows_read = 0

    with input_path.open(newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header row")

        with output_path.open("w", newline="", encoding="utf-8") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
            writer.writeheader()

            for line_no, row in enumerate(reader, start=2):
                rows_read += 1
                try:
                    out_row = build_baseline_row(row)
                    writer.writerow(out_row)
                    rows_written += 1
                except Exception as exc:  # noqa: BLE001 — scaffold must not crash
                    sys.stderr.write(
                        f"Row {line_no}: error {exc!r}; writing safe fallback row\n"
                    )
                    fallback = build_baseline_row(
                        {"issue": row.get("issue") or row.get("Issue") or "", "subject": "", "company": ""}
                    )
                    writer.writerow(fallback)
                    rows_written += 1

    return rows_read, rows_written


def _read_multiline_issue() -> str | None:
    """Read issue JSON from stdin until a blank line (or EOF after content)."""
    print("Issue JSON — paste below, then press Enter on an empty line:")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            if lines:
                break
            return None
        stripped = line.strip()
        if stripped.lower() in {"quit", "exit", ":q"}:
            return None
        if not stripped and lines:
            break
        if not stripped and not lines:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _format_actions(raw: str) -> str:
    text = (raw or "").strip()
    if not text or text == "[]":
        return "  (none)"
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return text


def _format_sources(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "  (none)"
    paths = [p.strip() for p in text.split("|") if p.strip()]
    if len(paths) <= 8:
        return "\n".join(f"  - {p}" for p in paths)
    head = "\n".join(f"  - {p}" for p in paths[:8])
    return f"{head}\n  ... and {len(paths) - 8} more"


def print_interactive_result(row: dict[str, str], *, llm_enabled: bool) -> None:
    """Pretty-print one agent decision for terminal review."""
    width = 72
    print()
    print("=" * width)
    print("AGENT DECISION")
    print("=" * width)
    print(f"  Status:          {row.get('status', '')}")
    print(f"  Request type:    {row.get('request_type', '')}")
    print(f"  Risk level:      {row.get('risk_level', '')}")
    print(f"  Product area:    {row.get('product_area', '')}")
    print(f"  PII detected:    {row.get('pii_detected', '')}")
    print(f"  Confidence:      {row.get('confidence_score', '')}")
    print(f"  Language:        {row.get('language', '')}")
    if llm_enabled:
        print("  LLM polisher:    enabled (response may be polished when eligible)")
    else:
        print("  LLM polisher:    disabled")
    print()
    print("Response:")
    print(textwrap.indent((row.get("response") or "").strip(), "  "))
    print()
    print("Justification:")
    print(textwrap.indent((row.get("justification") or "").strip(), "  "))
    print()
    print("Actions taken:")
    print(textwrap.indent(_format_actions(row.get("actions_taken") or ""), "  "))
    print()
    print("Source documents:")
    print(_format_sources(row.get("source_documents") or ""))
    print("=" * width)
    print()


def run_interactive(*, llm_enabled: bool) -> int:
    """REPL for single-ticket triage without a CSV file."""
    print(_INTERACTIVE_BANNER)
    ticket_no = 0
    while True:
        print(f"\n--- Ticket #{ticket_no + 1} ---")
        issue = _read_multiline_issue()
        if issue is None:
            print("Goodbye.")
            return 0
        if not issue:
            print("No issue text provided; try again or type quit.")
            continue

        subject = input("Subject (optional, Enter to skip): ").strip()
        company = input("Company (optional, Enter to skip): ").strip()

        input_row = {
            "issue": issue,
            "subject": subject,
            "company": company,
        }
        try:
            out_row = build_baseline_row(input_row)
        except Exception as exc:  # noqa: BLE001 — keep REPL alive
            print(f"Error processing ticket: {exc!r}", file=sys.stderr)
            continue

        ticket_no += 1
        print_interactive_result(out_row, llm_enabled=llm_enabled)

        stats = get_polish_stats()
        if llm_enabled and stats.attempted:
            print(
                f"LLM polish: attempted={stats.attempted} applied={stats.applied} "
                f"fallbacks={len(stats.fallback_errors)}"
            )

        again = input("Process another ticket? [Y/n]: ").strip().lower()
        if again in {"n", "no", "q", "quit", "exit"}:
            print("Goodbye.")
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run baseline support ticket triage scaffold")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help="Path to input CSV (default: support_tickets/support_tickets.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="Path to output CSV (default: support_tickets/output.csv)",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive single-ticket mode for live red-teaming (no CSV I/O)",
    )
    args = parser.parse_args(argv)

    reset_polish_stats()
    llm_cfg = load_llm_config()

    if args.interactive:
        return run_interactive(llm_enabled=llm_cfg.enabled)

    try:
        rows_read, rows_written = process_tickets(args.input, args.output)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Processed {rows_read} ticket(s); wrote {rows_written} row(s) to {args.output}")
    stats = get_polish_stats()
    if llm_cfg.enabled:
        print(
            f"LLM polisher: enabled (model={llm_cfg.model}); "
            f"attempted={stats.attempted} applied={stats.applied} "
            f"ineligible_skips={stats.skipped_ineligible}"
        )
    elif stats.skipped_disabled:
        pass  # polisher off — no extra line
    if rows_read != rows_written:
        print("Warning: read count and write count differ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
