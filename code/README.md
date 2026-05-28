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

Official structural check (provided by the challenge):

```bash
python code/scripts/validate_output.py
```

Extended local harness (tool schemas, corpus paths, PII echo, determinism):

```bash
python code/scripts/validate_submission.py
```

Use `--skip-determinism` only for quick iteration; run the full check before submitting.

Safety firewall sample checks:

```bash
python code/tests/test_safety_firewall.py
```

Corpus index stats:

```bash
python code/scripts/print_corpus_stats.py
python code/tests/test_corpus_index.py
python code/tests/test_retrieval_manual.py
python code/tests/test_routing.py
python code/tests/test_llm_eligibility.py
```

## Layout

| Module | Role |
|--------|------|
| `main.py` | CLI entry point; CSV read/write |
| `issue_parser.py` | Safe JSON parsing of `issue` conversations |
| `baseline.py` | Placeholder output fields per row |
| `pii.py` | Lightweight deterministic PII heuristics |
| `safety/` | Safety firewall (adversarial + PII classification, redaction) |
| `test_safety_firewall.py` | Synthetic + corpus coverage checks for firewall |
| `retrieval/` | Corpus indexer, BM25 retrieval, evidence grading |
| `test_retrieval_manual.py` | Visible-ticket retrieval smoke tests |
| `routing.py` | Deterministic routing + tool planning |
| `test_routing.py` | Routing/tool-planning smoke tests |
| `response.py` | Response composition + confidence calibration |
| `print_corpus_stats.py` | Index stats + path existence verification |
| `test_corpus_index.py` | Indexer unit-like checks |
| `paths.py` | Repo paths and output column order |
| `validate_output.py` | Structural output validation |

## Current behavior (scaffold only)

- Copies `issue`, `subject`, and `company` from input unchanged.
- Escalates all structurally valid tickets with low confidence (`0.25`).
- Uses `escalate_to_human` in `actions_taken` for escalated rows.
- Marks unparseable `issue` values as `request_type=invalid` without crashing.
- Does not retrieve from `data/` yet — `source_documents` is empty.
