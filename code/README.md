# Support Triage Agent (Deterministic + Optional Gated LLM)

This submission is **deterministic by default** (no network calls) and produces `support_tickets/output.csv` from `support_tickets/support_tickets.csv`.

It includes:

- Safety firewall (prompt-injection + PII detection + redaction)
- BM25 retrieval + evidence grading over the provided `data/` corpus
- Deterministic routing + tool planning
- Deterministic response composition grounded in approved snippets
- Optional gated LLM polisher that rewrites wording only and always falls back safely

## Setup

From the repository root (one level above `code/`):

**Step 1 — Create and activate a virtual environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

**Step 2 — Install dependencies:**
```bash
pip install -r code/requirements.txt
```

**Step 3 — Configure environment variables:**
```bash
cp .env.example .env
# Open .env and paste your OPENAI_API_KEY if you want the optional LLM polisher
```

The `.env` file must be placed at the **repository root** (next to the `code/` folder), not inside `code/`. The agent discovers it automatically via `code/paths.py`.

## Run

**Deterministic mode (default, no network calls, fully reproducible):**
```bash
python code/main.py
```

**With optional LLM polisher enabled:**
```bash
USE_LLM_POLISHER=true python code/main.py
```

Notes:

- With `USE_LLM_POLISHER=false` (default), output is fully deterministic and performs **no network calls**.
- No LLM call is made for ineligible rows (eligibility gate is conservative).
- The LLM can only replace the **`response` text**. All routing/decision fields remain deterministic.
- If the API key is missing, the API fails, times out, or validation fails, we **immediately fall back** to the deterministic response.

Optional custom paths:
```bash
python code/main.py --input support_tickets/support_tickets.csv --output support_tickets/output.csv
```

## Interactive Mode (Live Red-Teaming)

For testing individual tickets interactively (e.g., during a live interview or demo), use the `--interactive` flag:

```bash
USE_LLM_POLISHER=false python code/main.py --interactive
```

At the prompt, paste either a valid JSON conversation array or raw plain text. The agent wraps plain text automatically:

```
Issue — paste JSON array or plain text, then press Enter on an empty line:
Someone hacked my account, lock it now!

(Wrapped plain text as a single user message.)
========================================================================
AGENT DECISION
========================================================================
  Status:          escalated
  Risk level:      high
  ...
```

Press `n` to exit the loop.

## Synthetic hidden-set fixtures (local testing)

Generate a labeled synthetic dataset (separate from `support_tickets/support_tickets.csv`):

```bash
python code/scripts/generate_synthetic_fixtures.py
```

Outputs (deterministic with `random.seed(42)`):

- `code/tests/fixtures/synthetic_tickets.csv` — challenge-shaped inputs only (`Issue`, `Subject`, `Company`)
- `code/tests/fixtures/expected_metadata.json` — expected labels for rubric simulation (not fed to the agent)

Run the agent on synthetic tickets:

```bash
python code/main.py \
  --input code/tests/fixtures/synthetic_tickets.csv \
  --output code/tests/fixtures/synthetic_output.csv
```

Then validate with the custom rubric harness:

```bash
python code/scripts/validate_submission.py \
  --input code/tests/fixtures/synthetic_tickets.csv \
  --output code/tests/fixtures/synthetic_output.csv
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
- SHA-256 of identical back-to-back runs must match (confirmed during final rehearsal).

## Submission packaging

To reproduce the exact submitted ZIP from the repository root:

```bash
git log --oneline --all > git_history.txt
zip -r submission.zip code/ git_history.txt .env.example
```

Upload `submission.zip` and `support_tickets/output.csv` separately on the submission form.

## Architecture

See `code/ARCHITECTURE.md` for the system diagram, module responsibilities, and self-assessment.
