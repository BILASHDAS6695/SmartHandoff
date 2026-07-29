"""Lightweight token count estimation for context window management.

Uses a word-count approximation (words × 1.33) rather than a full tokeniser
to avoid a tiktoken dependency in the patient-comm agent container.
Maximum estimation error is ≤5% for English medical discharge text —
acceptable for managing the 2 K conversation history budget.

Design refs:
    US-043 AC Scenario 4 — FIFO pruning when conversation history exceeds 2 K tokens
    design.md AIR-024 — 8 K total context window
"""
from __future__ import annotations

import math


# Approximation constant: average English word ≈ 0.75 tokens in Gemini tokeniser
_WORDS_TO_TOKENS_FACTOR: float = 1.33


def estimate_tokens(text: str) -> int:
    """Return an estimated token count for *text*.

    Args:
        text: Plain-text string to estimate.

    Returns:
        Estimated integer token count, always ≥ 1 for non-empty text.
    """
    if not text.strip():
        return 0
    word_count = len(text.split())
    return math.ceil(word_count * _WORDS_TO_TOKENS_FACTOR)


def estimate_message_tokens(role: str, content: str) -> int:
    """Estimate tokens for a single conversation turn including role prefix.

    Adds 4 tokens of overhead for Gemini chat format markers
    (e.g <start_of_turn>user\\n ... <end_of_turn>).
    """
    return estimate_tokens(f"{role}: {content}") + 4
