#!/usr/bin/env python3
"""
Deterministic baseline scaffold for the MLE Hiring Challenge.

Reads support_tickets/support_tickets.csv and writes support_tickets/output.csv
with structurally valid decisions. Optional LLM polishing is env-gated (see .env.example).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from agent.baseline import build_baseline_row
from llm.config import load_llm_config
from llm.polisher import get_polish_stats, reset_polish_stats
from paths import DEFAULT_INPUT_CSV, DEFAULT_OUTPUT_CSV, OUTPUT_COLUMNS


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
    args = parser.parse_args(argv)

    reset_polish_stats()
    llm_cfg = load_llm_config()

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
