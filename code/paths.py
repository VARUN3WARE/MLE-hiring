"""Repository path constants for the support triage agent."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUPPORT_TICKETS_DIR = REPO_ROOT / "support_tickets"
DEFAULT_INPUT_CSV = SUPPORT_TICKETS_DIR / "support_tickets.csv"
DEFAULT_OUTPUT_CSV = SUPPORT_TICKETS_DIR / "output.csv"

OUTPUT_COLUMNS = [
    "issue",
    "subject",
    "company",
    "response",
    "product_area",
    "status",
    "request_type",
    "justification",
    "confidence_score",
    "source_documents",
    "risk_level",
    "pii_detected",
    "language",
    "actions_taken",
]
