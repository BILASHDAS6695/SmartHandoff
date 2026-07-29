"""Phase 1 urgency detection: keyword pattern matching (US-044, TASK-002).

Performs an O(n) scan of the patient message against compiled regex patterns
loaded from config/urgency_keywords.yaml. Target latency: <10ms per message.

Design ref:
    US-044 Technical Notes — Phase 1: fast regex keyword match (O(n), <10ms)
    US-044 AC Scenario 2 — configurable keyword list
    US-044 DoD — keyword detection runs BEFORE any LLM call
"""
from __future__ import annotations

import logging
import re
import time

from backend.app.agents.patient_comm.urgency.config_loader import load_urgency_keywords
from backend.app.agents.patient_comm.urgency.schemas import (
    DetectionPhase,
    UrgencyDetectionResult,
)

logger = logging.getLogger(__name__)


def detect_urgency_keyword(patient_message: str) -> UrgencyDetectionResult:
    """Run Phase 1 keyword scan against the patient message.

    Args:
        patient_message: Raw message text from the patient's chat input.
            Must be the original message text — no pre-processing or truncation.

    Returns:
        UrgencyDetectionResult with:
            - is_urgent=True, detection_phase=KEYWORD if a phrase matches
            - is_urgent=False, detection_phase=NONE if no keyword found
              (caller should proceed to Phase 2 Gemini classification)

    Security note:
        This function does NOT log the patient_message content — only the
        matched keyword phrase and elapsed time are logged.
        The raw message may contain PHI (diagnosis, symptoms) and must
        never appear in Cloud Logging output.
    """
    patterns: list[re.Pattern[str]] = load_urgency_keywords()

    t_start = time.perf_counter()
    matched: str | None = None

    for pattern in patterns:
        if pattern.search(patient_message):
            matched = pattern.pattern
            break

    elapsed_ms = (time.perf_counter() - t_start) * 1_000

    if matched:
        # Build a safe, non-PHI summary from the matched keyword only.
        # The raw patient message MUST NOT appear in the summary.
        summary = f"Urgency keyword detected: '{_extract_phrase(matched)}'"[:100]

        logger.info(
            "urgency_keyword_detected",
            extra={
                "matched_phrase": _extract_phrase(matched),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

        return UrgencyDetectionResult(
            is_urgent=True,
            detection_phase=DetectionPhase.KEYWORD,
            matched_phrase=_extract_phrase(matched),
            confidence=None,  # Phase 2 confidence not applicable for keyword match
            message_summary=summary,
        )

    logger.debug(
        "urgency_keyword_no_match",
        extra={"elapsed_ms": round(elapsed_ms, 2), "pattern_count": len(patterns)},
    )

    return UrgencyDetectionResult(
        is_urgent=False,
        detection_phase=DetectionPhase.NONE,
        matched_phrase=None,
        confidence=None,
        message_summary=None,
    )


def _extract_phrase(compiled_pattern: str) -> str:
    """Extract the human-readable phrase from a compiled regex pattern string.

    Strips word-boundary anchors and re.escape artefacts to return the
    original keyword phrase as it appeared in urgency_keywords.yaml.

    Example:
        r'\\bchest\\ pain\\b'  →  'chest pain'
    """
    phrase = compiled_pattern
    # Remove word boundary anchors added in config_loader.py
    phrase = phrase.lstrip(r"\b").rstrip(r"\b")
    # Unescape re.escape artefacts (e.g. '\ ' → ' ')
    phrase = re.sub(r"\\(.)", r"\1", phrase)
    return phrase.strip()
