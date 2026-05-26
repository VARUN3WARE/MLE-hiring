# Support Triage Agent — Baseline Scaffold

Deterministic, stdlib-only baseline that reads `support_tickets/support_tickets.csv` and writes `support_tickets/output.csv` with conservative placeholder decisions. No network calls and no ticket-specific hardcoded answers.

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r code/requirements.txt
```

## Run

```bash
python code/main.py
```

Optional paths:

```bash
python code/main.py --input support_tickets/support_tickets.csv --output support_tickets/output.csv
```

## Validate

```bash
python code/validate_output.py
```

## Layout

| Module | Role |
|--------|------|
| `main.py` | CLI entry point; CSV read/write |
| `issue_parser.py` | Safe JSON parsing of `issue` conversations |
| `baseline.py` | Placeholder output fields per row |
| `pii.py` | Lightweight deterministic PII heuristics |
| `paths.py` | Repo paths and output column order |
| `validate_output.py` | Structural output validation |

## Current behavior (scaffold only)

- Copies `issue`, `subject`, and `company` from input unchanged.
- Escalates all structurally valid tickets with low confidence (`0.25`).
- Uses `escalate_to_human` in `actions_taken` for escalated rows.
- Marks unparseable `issue` values as `request_type=invalid` without crashing.
- Does not retrieve from `data/` yet — `source_documents` is empty.
