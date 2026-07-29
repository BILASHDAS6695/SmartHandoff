"""Phase 2 urgency detection: Gemini Flash semantic classification (US-044, TASK-003).

Called ONLY when Phase 1 keyword matching returns is_urgent=False.
Uses gemini-1.5-flash in JSON output mode with structured Pydantic validation.
Target latency: ~500ms.

Design refs:
    design.md §7.3 AIR-020 — Vertex AI JSON output mode; Pydantic validation;
                              malformed output → retry (max 2) then safe fallback.
    design.md §7.3 AIR-021 — minimum-necessary PHI in prompts; no PHI logged.
    design.md §4.1 TR-006 — gemini-1.5-flash for chatbot/urgency path (not Pro).
    US-044 Technical Notes — confidence threshold: 0.8.
    US-044 DoD — structured output: {urgency: bool, confidence: float}.
"""
from __future__ import annotations

import json
import logging

from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from backend.app.agents.patient_comm.urgency.schemas import (
    DetectionPhase,
    GeminiUrgencyClassification,
    UrgencyDetectionResult,
)

logger = logging.getLogger(__name__)

# Urgency classification threshold (US-044 DoD)
_URGENCY_CONFIDENCE_THRESHOLD: float = 0.8

# Maximum LLM retries before safe fallback (design.md AIR-020)
_MAX_RETRIES: int = 2

# Urgency classification system prompt.
# PHI minimisation (AIR-021): the prompt does not include patient name, MRN, or DOB.
# Only the raw message text (which the patient typed) is passed.
_SYSTEM_PROMPT = (
    "You are a medical urgency classifier for a hospital patient chatbot. "
    "Your ONLY task is to determine whether a patient's message contains a "
    "life-threatening medical emergency signal that requires immediate action "
    "(e.g. chest pain, difficulty breathing, severe bleeding, loss of consciousness, stroke, suicidal intent). "
    "Respond ONLY with valid JSON matching this schema: "
    '{"urgency": <boolean>, "confidence": <float 0.0-1.0>}. '
    "Do not include any other text. "
    "If uncertain, set confidence below 0.8 and urgency to false."
)


async def classify_urgency_semantic(patient_message: str) -> UrgencyDetectionResult:
    """Run Phase 2 semantic urgency classification using Gemini Flash.

    Args:
        patient_message: The patient's raw message text. Passed to Gemini
            as-is (minimum necessary context). Never logged.

    Returns:
        UrgencyDetectionResult:
            - is_urgent=True, detection_phase=SEMANTIC if confidence >= 0.8
            - is_urgent=False, detection_phase=NONE otherwise
            - On LLM failure after retries: safe fallback is_urgent=False
              (safer to let the normal pipeline proceed than to false-positive)

    Security note:
        patient_message is sent to Vertex AI in the prompt.
        It is NOT logged — only encounter_id and elapsed_ms are logged.
        Vertex AI is NOT configured with log_to_bigquery or prompt logging.
    """
    llm = ChatVertexAI(
        model_name="gemini-1.5-flash",
        temperature=0.0,
        response_mime_type="application/json",
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=patient_message),
    ]

    classification: GeminiUrgencyClassification | None = None

    for attempt in range(1, _MAX_RETRIES + 2):  # attempts: 1, 2, 3 (max 2 retries)
        try:
            response = await llm.ainvoke(messages)
            raw_content = response.content

            parsed = json.loads(raw_content)
            classification = GeminiUrgencyClassification(**parsed)
            break  # Successful parse — exit retry loop

        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            logger.warning(
                "urgency_semantic_classification_retry",
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            if attempt > _MAX_RETRIES:
                # Safe fallback: assume non-urgent (design.md AIR-020)
                # False negative risk is lower than causing alert fatigue via false positives
                logger.error(
                    "urgency_semantic_classification_failed_safe_fallback",
                    extra={"max_retries": _MAX_RETRIES},
                )
                return UrgencyDetectionResult(
                    is_urgent=False,
                    detection_phase=DetectionPhase.NONE,
                    matched_phrase=None,
                    confidence=None,
                    message_summary=None,
                )

    # Apply threshold
    is_urgent = (
        classification.urgency and classification.confidence >= _URGENCY_CONFIDENCE_THRESHOLD
    )

    if is_urgent:
        summary = "Semantic urgency signal detected by AI classifier"[:100]
        logger.info(
            "urgency_semantic_detected",
            extra={
                "confidence": classification.confidence,
                "threshold": _URGENCY_CONFIDENCE_THRESHOLD,
            },
        )
        return UrgencyDetectionResult(
            is_urgent=True,
            detection_phase=DetectionPhase.SEMANTIC,
            matched_phrase=None,
            confidence=classification.confidence,
            message_summary=summary,
        )

    logger.debug(
        "urgency_semantic_no_match",
        extra={
            "urgency_flag": classification.urgency,
            "confidence": classification.confidence,
            "threshold": _URGENCY_CONFIDENCE_THRESHOLD,
        },
    )

    return UrgencyDetectionResult(
        is_urgent=False,
        detection_phase=DetectionPhase.NONE,
        matched_phrase=None,
        confidence=classification.confidence,
        message_summary=None,
    )
