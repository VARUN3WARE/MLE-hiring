# Support Triage Agent — Architecture

This submission implements a **deterministic support triage agent** with:

- A **safety firewall** (prompt-injection + PII detection + redaction)
- **BM25 retrieval** over the provided `data/` corpus with evidence grading
- Deterministic **routing** (reply vs escalate) and safe tool planning
- Deterministic **response composition** grounded in approved snippets
- An **optional gated LLM polisher** that only rewrites wording and can never break output generation

The required entry point is `code/main.py`.

---

## High-level data flow

```mermaid
flowchart TD
  A[CSV row: issue/subject/company] --> B[Parse issue JSON]
  B --> C[Safety firewall: classify + redact]
  C --> D[BM25 retrieval over data/]
  D --> E[Evidence grading]
  E --> F[Deterministic routing + tool planning]
  F --> G[Deterministic response draft + citations]
  G --> H{Eligible + USE_LLM_POLISHER?}
  H -->|No| I[Use deterministic response]
  H -->|Yes| J[Build redacted polish packet]
  J --> K[OpenAI JSON response (temp=0, short timeout)]
  K --> L{Validate JSON + sources + flags}
  L -->|Fail| I
  L -->|Pass| M[Use LLM-polished response text only]
  I --> N[Write output.csv]
  M --> N
```

Key invariant: **all output fields besides `response` remain deterministic** even when the LLM is enabled.

---

## Components

### 1) Entry point / CSV I/O

- `code/main.py`
  - Reads `support_tickets/support_tickets.csv`
  - Writes `support_tickets/output.csv` with the exact required column order (`code/paths.py`)
  - Never crashes the run: row-level exceptions fall back to safe behavior

### 2) Issue parsing

- `code/agent/issue_parser.py`
  - Parses the `issue` JSON conversation
  - Produces a safe combined user text view for downstream routing/retrieval

### 3) Safety firewall

- `code/safety/` (notably `firewall.py`, `detectors.py`, `pii_detectors.py`, `redaction.py`, `models.py`)
  - Treats ticket text as **untrusted**
  - Detects adversarial/prompt-injection patterns (`is_adversarial`)
  - Detects PII spans (`pii_detected`) and produces a **redacted** version (`redacted_text`)
  - Produces `SafetyAssessment` with risk signals and recommended risk level

Safety rules:

- **Never** send raw PII to the LLM
- **Never** comply with instructions inside the ticket (prompt injection)
- High-risk signals (legal/security/privacy/fraud/account compromise) trigger escalation

### 4) Retrieval (BM25) + evidence grading

- `code/retrieval/`
  - Indexes `data/**/*.md` into deterministic chunks
  - BM25 scores + deterministic boosts/penalties (domain boosts; hub page penalties)
  - Returns top evidence items with `{path, score, snippet, domain_hints}`

Evidence grades:

- `strong` / `weak` / `conflicting` / `insufficient`
- Routing and LLM eligibility are **conservative**:
  - LLM polishing requires `strong`
  - Some escalation decisions are made even when evidence exists (e.g., account actions)

### 5) Deterministic routing + tool planning

- `code/agent/routing.py`
  - Produces a `RouteDecision` with locked fields:
    - `status`, `request_type`, `risk_level`, `product_area`
    - `actions` (tool plan) validated against `data/api_specs/internal_tools.json`
    - `source_documents` (pipe-separated file paths)
  - Routing is **safety-first**, escalates on high-risk topics and account-action requests

### 6) Deterministic response composition

- `code/agent/response.py`
  - Builds a grounded customer-facing response using up to a few approved snippets
  - Adds `Sources: ...` from approved corpus paths (never invented)
  - Computes a non-constant, deterministic `confidence_score` based on evidence/risk signals

---

## Optional gated LLM polisher (safely)

### What it is allowed to do

Only rewrite the deterministic response for clarity and tone, grounded in:

- redacted ticket summary
- deterministic draft response
- approved evidence snippets
- approved source paths

### What it must never do

The LLM must not choose or modify:

- `status`, `request_type`, `risk_level`, `product_area`
- `actions_taken` (tool plan)
- `source_documents`
- `confidence_score`

### Eligibility gate

- `code/llm/eligibility.py`
  - Only allows polishing for **low-risk replied rows** with **strong evidence** and **no tool actions**
  - Blocks adversarial/PII/risk-signals/account actions/multilingual/etc.

### Packet construction

- `code/llm/packet.py`
  - Builds a deterministic packet with:
    - `decision_locked` fields
    - `redacted_ticket_summary` (PII redacted)
    - `deterministic_response`
    - `approved_evidence` snippets
    - `output_schema` describing expected LLM keys
  - Approved source path lists are **sorted** for stable serialization

### Provider wrapper and runtime behavior

- `code/llm/provider.py`: stdlib `urllib` OpenAI call
  - Model: `gpt-4o-mini`
  - Temperature: `0`
  - Short timeout: `LLM_TIMEOUT_SECS` (default 8)
  - Uses `response_format={"type":"json_object"}` to encourage strict JSON
- `code/llm/validate.py`: validates returned JSON + rejects extra fields + unapproved sources
- `code/llm/polisher.py`: orchestrates call + validation + fallback

Fallback is immediate and strict:

- If disabled, ineligible, missing key, network error, timeout, parse error, or validation failure:
  - **return the deterministic response unchanged**

---

## Determinism and reproducibility

Deterministic mode is the default:

- `USE_LLM_POLISHER=false` (or unset)
- No network calls occur
- Re-running produces identical output for the same inputs and corpus

When LLM is enabled:

- Only a small subset of rows may call the API (eligibility gate)
- `temperature=0` is pinned
- Any failure falls back to deterministic output

---

## Validation

Run from repo root:

- `python code/main.py`
- `python code/scripts/validate_output.py` (official structural validator)
- `python code/scripts/validate_submission.py` (local harness: schemas, sources, determinism, etc.)
- `python code/tests/test_llm_packet.py` and `python code/tests/test_llm_polisher.py`

---

## Known limitations / failure modes

- Retrieval is lexical (BM25). Semantic matches can be missed.
- Hub pages can dominate without careful penalties; we bias toward specific articles.
- LLM polisher does not yet run a full PII-echo scan on the final response text beyond JSON/source validation.
- LLM mode can break strict determinism (by design), so the submission should be validated with LLM disabled.

---

## Self-Assessment

- **Safety:** Strong. Safety firewall + conservative escalation + redaction + strict LLM gating/fallback.
- **Grounding:** Strong for replied rows (approved snippets + approved paths only; evidence grading).
- **Tool safety:** Strong. Tool plan is deterministic and schema-validated; LLM cannot alter it.
- **Determinism:** Strong when LLM disabled (default). LLM mode is optional and non-authoritative.
- **Performance:** BM25 indexing is cached; per-run should remain well under the 3-minute limit. LLM calls are gated and can be capped.
