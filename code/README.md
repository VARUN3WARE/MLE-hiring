# Support Triage Agent (Deterministic + Optional Gated LLM)

This submission is **deterministic by default** (no network calls) and produces `support_tickets/output.csv` from `support_tickets/support_tickets.csv`.

It includes:

- Safety firewall (prompt-injection + PII detection + redaction)
- BM25 retrieval + evidence grading over the provided `data/` corpus
- Deterministic routing + tool planning
- Deterministic response composition grounded in approved snippets
- Optional gated LLM polisher that rewrites wording only and always falls back safely

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

### Optional LLM polisher (off by default)

Copy `.env.example` to `.env`, set `OPENAI_API_KEY`, then:

```bash
USE_LLM_POLISHER=true python code/main.py
```

Notes:

- With `USE_LLM_POLISHER=false` (default), output is fully deterministic and performs **no network calls**.
- No LLM call is made for ineligible rows (eligibility gate is conservative).
- The LLM can only replace the **`response` text**. All routing/decision fields remain deterministic.
- If the API key is missing, the API fails, times out, or validation fails, we **immediately fall back** to the deterministic response.

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

LLM layer unit tests (no network required):

```bash
python code/tests/test_llm_packet.py
python code/tests/test_llm_polisher.py
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
| `llm/` | Eligibility gate, polish packets, optional OpenAI polisher |

## Reproducibility checklist

- Deterministic run: `USE_LLM_POLISHER=false python code/main.py`
- Output path: `support_tickets/output.csv`
- Validate structure: `python code/scripts/validate_output.py`
- Validate submission locally: `python code/scripts/validate_submission.py`

## Architecture

See `code/ARCHITECTURE.md` for the system diagram, module responsibilities, and self-assessment.
