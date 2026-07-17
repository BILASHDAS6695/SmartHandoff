---
id: TASK-003
title: "UrgencyDetector Phase 2 — Gemini Flash Semantic Classification & Combined UrgencyDetector"
user_story: US-044
epic: EP-008
sprint: 2
layer: Backend / AI Agent
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-044/TASK-001, US-044/TASK-002]
---

# TASK-003: UrgencyDetector Phase 2 — Gemini Flash Semantic Classification & Combined UrgencyDetector

> **Story:** US-044 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

Phase 2 runs only when Phase 1 (TASK-002) finds no keyword match. It uses `gemini-1.5-flash` in JSON output mode to classify whether the patient message contains a medical urgency signal, returning structured output `{urgency: bool, confidence: float}`. A score of `confidence >= 0.8` triggers the urgency response path (same as a keyword match).

This task also implements the `UrgencyDetector` facade class that orchestrates both phases in sequence and returns a single `UrgencyDetectionResult` — the interface consumed by TASK-005 (pipeline integration).

**Design references:**
- design.md §3.1 — Patient Communication Agent: semantic urgency classification
- design.md §4.1 TR-006 — `gemini-1.5-flash` (not Pro) for the chatbot path
- design.md §7.3 AIR-020 — all Vertex AI calls use `response_mime_type="application/json"` with Pydantic schema validation; malformed output triggers retry (max 2) then fallback
- design.md §7.3 AIR-021 — PHI must be minimal in LLM prompts; minimum-necessary principle enforced
- US-044 Technical Notes — Phase 2: Gemini classification only if keyword match fails (~500ms)
- US-044 DoD — semantic urgency threshold: 0.8 on `{urgency: bool, confidence: float}` structured output

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 3 | Gemini returns `{urgency: true, confidence: 0.93}` for "my heart is racing really fast and I feel dizzy" → `is_urgent=True` |
| Scenario 4 | Gemini returns `{urgency: false, confidence: 0.12}` for "when should I take my metformin?" → `is_urgent=False` |
| Scenario 1 | `UrgencyDetector.detect()` returns verdict within 500ms for Phase 2 path |

---

## Implementation Steps

### 1. Create Phase 2 semantic classifier and facade modules

```bash
touch backend/app/agents/patient_comm/urgency/semantic_classifier.py
touch backend/app/agents/patient_comm/urgency/detector.py
```

### 2. Implement `backend/app/agents/patient_comm/urgency/semantic_classifier.py`

```python
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
```

### 3. Implement `backend/app/agents/patient_comm/urgency/detector.py`

```python
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
```

---

## Validation Checklist

```bash
# Syntax check
python -c "
import ast, pathlib
for f in [
    'backend/app/agents/patient_comm/urgency/semantic_classifier.py',
    'backend/app/agents/patient_comm/urgency/detector.py',
]:
    ast.parse(pathlib.Path(f).read_text())
    print(f'{f} — syntax OK')
"

# Schema threshold assertion
python -c "
from backend.app.agents.patient_comm.urgency.schemas import GeminiUrgencyClassification

# Exactly at threshold (0.8)
c = GeminiUrgencyClassification(urgency=True, confidence=0.8)
assert c.urgency and c.confidence >= 0.8
print('confidence=0.8 at threshold ✓')

# Below threshold (0.79)
c2 = GeminiUrgencyClassification(urgency=True, confidence=0.79)
assert not (c2.urgency and c2.confidence >= 0.8), 'Should NOT trigger urgency'
print('confidence=0.79 below threshold — no urgency ✓')
"

# Detector imports without error
python -c "
from backend.app.agents.patient_comm.urgency.detector import UrgencyDetector
d = UrgencyDetector()
print(f'UrgencyDetector instantiated: {d} ✓')
"
```

---

## Definition of Done

- [ ] `backend/app/agents/patient_comm/urgency/semantic_classifier.py` created
- [ ] `backend/app/agents/patient_comm/urgency/detector.py` created with `UrgencyDetector` class
- [ ] `classify_urgency_semantic()` uses `gemini-1.5-flash` (not Pro) with `response_mime_type="application/json"`
- [ ] Retry logic: max 2 retries on JSON/validation error; safe `is_urgent=False` fallback on exhaustion (AIR-020)
- [ ] Confidence threshold `0.8` enforced in classifier — not hardcoded in detector facade
- [ ] PHI protection: `patient_message` never logged; only `confidence`, `threshold`, `attempt` in logger calls
- [ ] `UrgencyDetector.detect()` calls Phase 1 synchronously first; Phase 2 only if Phase 1 returns `NONE`
- [ ] Syntax check passes for both modules
- [ ] Schema threshold assertion script passes
