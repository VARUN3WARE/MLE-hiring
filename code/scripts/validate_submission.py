#!/usr/bin/env python3
"""
Local submission validation harness (private checks beyond validate_output.py).

Validates structural compliance, tool schemas, corpus paths, PII echo, and
deterministic agent output. No network calls.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Allow running as `python code/scripts/validate_submission.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import DEFAULT_INPUT_CSV, DEFAULT_OUTPUT_CSV, OUTPUT_COLUMNS, REPO_ROOT
from safety.pii_leak import find_pii_leaks, input_text_for_row
from schemas.tool_schema import load_tool_specs, validate_actions

VALID_STATUS = {"replied", "escalated"}
VALID_REQUEST_TYPE = {"product_issue", "feature_request", "bug", "invalid"}
VALID_RISK_LEVEL = {"low", "medium", "high", "critical"}
VALID_PII_DETECTED = {"true", "false"}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors


def _count_data_rows(csv_path: Path) -> int:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def _read_output_rows(output_path: Path) -> tuple[list[str] | None, list[dict[str, str]]]:
    with output_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        rows = list(reader)
    return headers, rows


def _read_input_rows(input_path: Path) -> list[dict[str, str]]:
    with input_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _normalize_input_row(row: dict[str, str]) -> dict[str, str]:
    lowered = {k.strip().lower(): (v if v is not None else "") for k, v in row.items()}
    return {
        "issue": lowered.get("issue", ""),
        "subject": lowered.get("subject", ""),
        "company": lowered.get("company", ""),
    }


def check_files_exist(report: ValidationReport, input_path: Path, output_path: Path) -> None:
    if not input_path.is_file():
        report.add_error(f"Input not found: {input_path}")
    if not output_path.is_file():
        report.add_error(f"Output not found: {output_path}")


def check_headers_and_row_count(
    report: ValidationReport,
    input_path: Path,
    headers: list[str] | None,
    rows: list[dict[str, str]],
) -> None:
    if headers is None:
        report.add_error("Output CSV has no header row")
        return

    if list(headers) != OUTPUT_COLUMNS:
        report.add_error(
            f"Output header order mismatch.\n"
            f"  expected: {OUTPUT_COLUMNS}\n"
            f"  got:      {list(headers)}"
        )

    input_count = _count_data_rows(input_path)
    if len(rows) != input_count:
        report.add_error(
            f"Row count mismatch: input has {input_count}, output has {len(rows)}"
        )


def check_enums(report: ValidationReport, rows: list[dict[str, str]]) -> None:
    for index, row in enumerate(rows, start=1):
        status = (row.get("status") or "").strip().lower()
        if status not in VALID_STATUS:
            report.add_error(f"Row {index}: invalid status '{status}'")

        request_type = (row.get("request_type") or "").strip().lower()
        if request_type not in VALID_REQUEST_TYPE:
            report.add_error(f"Row {index}: invalid request_type '{request_type}'")

        risk = (row.get("risk_level") or "").strip().lower()
        if risk and risk not in VALID_RISK_LEVEL:
            report.add_error(f"Row {index}: invalid risk_level '{risk}'")
        elif not risk:
            report.add_warning(f"Row {index}: empty risk_level")

        pii_flag = (row.get("pii_detected") or "").strip().lower()
        if pii_flag not in VALID_PII_DETECTED:
            report.add_error(f"Row {index}: invalid pii_detected '{pii_flag}'")

        conf = (row.get("confidence_score") or "").strip()
        if conf:
            try:
                value = float(conf)
                if not 0.0 <= value <= 1.0:
                    report.add_error(f"Row {index}: confidence_score {value} out of [0, 1]")
            except ValueError:
                report.add_error(f"Row {index}: confidence_score '{conf}' is not a float")
        else:
            report.add_warning(f"Row {index}: empty confidence_score")

        if not (row.get("response") or "").strip():
            report.add_warning(f"Row {index}: empty response")


def check_actions(report: ValidationReport, rows: list[dict[str, str]], specs: dict) -> None:
    for index, row in enumerate(rows, start=1):
        raw = (row.get("actions_taken") or "").strip()
        if not raw:
            report.add_warning(f"Row {index}: empty actions_taken (use '[]' if none)")
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            report.add_error(f"Row {index}: actions_taken invalid JSON ({exc.msg})")
            continue
        report.errors.extend(validate_actions(parsed, specs, index))


def check_source_documents(report: ValidationReport, rows: list[dict[str, str]]) -> None:
    for index, row in enumerate(rows, start=1):
        raw = (row.get("source_documents") or "").strip()
        if not raw:
            continue
        for doc_path in raw.split("|"):
            doc_path = doc_path.strip()
            if not doc_path:
                continue
            resolved = (REPO_ROOT / doc_path).resolve()
            try:
                resolved.relative_to(REPO_ROOT.resolve())
            except ValueError:
                report.add_error(f"Row {index}: source_documents path escapes repo: {doc_path}")
                continue
            if not resolved.is_file():
                report.add_error(f"Row {index}: source_documents file not found: {doc_path}")


def check_pii_echo(
    report: ValidationReport,
    input_rows: list[dict[str, str]],
    output_rows: list[dict[str, str]],
) -> None:
    if len(input_rows) != len(output_rows):
        return

    for index, (in_row, out_row) in enumerate(zip(input_rows, output_rows), start=1):
        normalized = _normalize_input_row(in_row)
        ticket_text = input_text_for_row(normalized["issue"], normalized["subject"])
        response = out_row.get("response") or ""
        leaks = find_pii_leaks(ticket_text, response)
        for fragment in leaks:
            report.add_error(
                f"Row {index}: response appears to echo input PII/token: {fragment!r}"
            )


def check_input_fields_preserved(
    report: ValidationReport,
    input_rows: list[dict[str, str]],
    output_rows: list[dict[str, str]],
) -> None:
    if len(input_rows) != len(output_rows):
        return

    for index, (in_row, out_row) in enumerate(zip(input_rows, output_rows), start=1):
        normalized = _normalize_input_row(in_row)
        for field in ("issue", "subject", "company"):
            if (out_row.get(field) or "") != normalized[field]:
                report.add_error(
                    f"Row {index}: output '{field}' does not match input (must be copied verbatim)"
                )


def check_determinism(
    report: ValidationReport,
    input_path: Path,
    reference_output: Path,
) -> None:
    from main import process_tickets

    with tempfile.TemporaryDirectory(prefix="mle_validate_") as tmp_dir:
        tmp = Path(tmp_dir)
        run_a = tmp / "run_a.csv"
        run_b = tmp / "run_b.csv"
        process_tickets(input_path, run_a)
        process_tickets(input_path, run_b)

        hash_a = hashlib.sha256(run_a.read_bytes()).hexdigest()
        hash_b = hashlib.sha256(run_b.read_bytes()).hexdigest()
        if hash_a != hash_b:
            report.add_error(
                "Determinism check failed: two consecutive agent runs produced different output"
            )
            return

        ref_hash = hashlib.sha256(reference_output.read_bytes()).hexdigest()
        if hash_a != ref_hash:
            report.add_warning(
                "Determinism check: agent re-run matches itself but differs from committed output.csv "
                "(regenerate output with code/main.py)"
            )


def validate(
    input_path: Path,
    output_path: Path,
    *,
    skip_determinism: bool = False,
    tools_path: Path | None = None,
) -> ValidationReport:
    report = ValidationReport()
    check_files_exist(report, input_path, output_path)
    if not report.ok and (not input_path.is_file() or not output_path.is_file()):
        return report

    headers, output_rows = _read_output_rows(output_path)
    input_rows = _read_input_rows(input_path)
    specs = load_tool_specs(tools_path)

    check_headers_and_row_count(report, input_path, headers, output_rows)
    check_enums(report, output_rows)
    check_actions(report, output_rows, specs)
    check_source_documents(report, output_rows)
    check_input_fields_preserved(report, input_rows, output_rows)
    check_pii_echo(report, input_rows, output_rows)

    if not skip_determinism:
        check_determinism(report, input_path, output_path)

    return report


def print_report(report: ValidationReport, input_path: Path, output_path: Path) -> None:
    print("=" * 60)
    print("MLE Hiring Challenge — Local Submission Validation")
    print("=" * 60)
    print(f"\nInput:  {input_path}")
    print(f"Output: {output_path}")

    if report.errors:
        print(f"\n❌ ERRORS ({len(report.errors)}):")
        for message in report.errors[:25]:
            print(f"   • {message}")
        if len(report.errors) > 25:
            print(f"   ... and {len(report.errors) - 25} more")

    if report.warnings:
        print(f"\n⚠️  WARNINGS ({len(report.warnings)}):")
        for message in report.warnings[:15]:
            print(f"   • {message}")
        if len(report.warnings) > 15:
            print(f"   ... and {len(report.warnings) - 15} more")

    if report.ok:
        print("\n✅ PASS: Local submission checks passed.")
        print("   Run code/validate_output.py for the official structural validator.")
    else:
        print(f"\n❌ FAIL: {len(report.errors)} error(s). Fix before submitting.")

    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extended local submission validation")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument(
        "--skip-determinism",
        action="store_true",
        help="Skip re-running the agent twice (faster, not recommended before submit)",
    )
    parser.add_argument(
        "--tools",
        type=Path,
        default=None,
        help="Path to internal_tools.json (default: data/api_specs/internal_tools.json)",
    )
    args = parser.parse_args(argv)

    report = validate(
        args.input,
        args.output,
        skip_determinism=args.skip_determinism,
        tools_path=args.tools,
    )
    print_report(report, args.input, args.output)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
