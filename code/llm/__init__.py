"""Gated LLM drafting layer (Phase 9/10).

This package intentionally contains only gates/packets/validators.
No network calls from this package unless explicitly invoked by a caller.
"""

from llm.config import LLMConfig, load_llm_config
from llm.eligibility import LLMRowContext, is_llm_eligible
from llm.packet import LLMPolishPacket, build_polish_packet
from llm.polisher import maybe_polish_response
from llm.validate import ValidatedLLMOutput, validate_llm_output

__all__ = [
    "LLMConfig",
    "LLMRowContext",
    "LLMPolishPacket",
    "ValidatedLLMOutput",
    "build_polish_packet",
    "is_llm_eligible",
    "load_llm_config",
    "maybe_polish_response",
    "validate_llm_output",
]

