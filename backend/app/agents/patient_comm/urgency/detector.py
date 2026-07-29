"""UrgencyDetector facade — orchestrates Phase 1 and Phase 2 (US-044, TASK-003).

The UrgencyDetector is the single entry point consumed by the chatbot pipeline
(TASK-005). Callers invoke `await detector.detect(message)` and receive a
`UrgencyDetectionResult` without needing to know which phase triggered it.

Execution flow:
    1. Phase 1 (keyword matching, <10ms, synchronous)
       → If match found: return KEYWORD result immediately (skip Phase 2)
    2. Phase 2 (Gemini semantic classification, ~500ms, async)
       → If confidence >= 0.8: return SEMANTIC result
       → Else: return NONE result (proceed to normal chatbot pipeline)

Design refs:
    US-044 DoD — urgency detection runs BEFORE LLM call; not as post-processing
    US-044 Technical Notes — two-phase detection sequence
    design.md §3.1 — Patient Communication Agent: urgency detection, escalation routing
"""
from __future__ import annotations

from backend.app.agents.patient_comm.urgency.keyword_matcher import detect_urgency_keyword
from backend.app.agents.patient_comm.urgency.schemas import UrgencyDetectionResult
from backend.app.agents.patient_comm.urgency.semantic_classifier import classify_urgency_semantic


class UrgencyDetector:
    """Two-phase urgency detector for the patient chatbot pipeline.

    Usage (in TASK-005 pipeline integration):
        detector = UrgencyDetector()
        result = await detector.detect(patient_message)
        if result.is_urgent:
            return await emergency_handler.handle(result, encounter_id, patient_first_name)
        # ... proceed to normal chatbot LLM call
    """

    async def detect(self, patient_message: str) -> UrgencyDetectionResult:
        """Run Phase 1 then Phase 2 (if needed) and return the combined verdict.

        Args:
            patient_message: Raw patient chat message. Never logged by this class.

        Returns:
            UrgencyDetectionResult — is_urgent=True if either phase triggers.
        """
        # Phase 1: keyword pattern matching (synchronous, <10ms)
        phase1_result = detect_urgency_keyword(patient_message)
        if phase1_result.is_urgent:
            return phase1_result

        # Phase 2: Gemini semantic classification (async, ~500ms)
        phase2_result = await classify_urgency_semantic(patient_message)
        return phase2_result
