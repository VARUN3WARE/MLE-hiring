"""Safety firewall: classify untrusted ticket text before retrieval or generation."""

from safety.firewall import classify_ticket
from safety.models import SafetyAssessment

__all__ = ["SafetyAssessment", "classify_ticket"]
