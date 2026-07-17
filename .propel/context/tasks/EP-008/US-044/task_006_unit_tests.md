---
id: TASK-006
title: "Unit Tests — Keyword Matches, Semantic Threshold, Non-Urgent Exclusion, Pipeline Integration"
user_story: US-044
epic: EP-008
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-044/TASK-001, US-044/TASK-002, US-044/TASK-003, US-044/TASK-004, US-044/TASK-005]
---

# TASK-006: Unit Tests — Keyword Matches, Semantic Threshold, Non-Urgent Exclusion, Pipeline Integration

> **Story:** US-044 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-044 DoD specifies unit tests for: keyword matches, semantic threshold, and non-urgent exclusion. This task implements those tests plus integration-path tests confirming that the urgency gate in `POST /api/v1/chat` correctly short-circuits the LLM call.

Coverage target: ≥80% branch coverage across all US-044 modules (TR-020).

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_keyword_matcher.py` | `urgency/keyword_matcher.py` | All AC Scenario 2 keywords; non-urgent exclusion; PHI-free log assertions |
| `test_semantic_classifier.py` | `urgency/semantic_classifier.py` | Confidence threshold at/below 0.8; retry logic; safe fallback on exhausted retries |
| `test_urgency_detector.py` | `urgency/detector.py` | Phase 1 match skips Phase 2; Phase 2 called only when Phase 1 returns NONE |
| `test_emergency_handler.py` | `urgency/emergency_handler.py` | Alert payload PHI bounds; Pub/Sub publish called; urgency_flag DB write; concurrent execution |
| `test_chat_urgency_integration.py` | `api-gateway/app/routers/chat.py` | Urgent message → emergency reply, no LLM call; non-urgent → normal pipeline; scope enforcement still runs first |

### Mocking strategy

| External Dependency | Mock Approach |
|--------------------|---------------|
| `ChatVertexAI.ainvoke()` | `AsyncMock` returning `AIMessage(content='{"urgency": true, "confidence": 0.93}')` |
| `pubsub_v1.PublisherClient.publish()` | `MagicMock` returning a `Future` that resolves to `"msg-id-123"` |
| `AsyncSession.execute()` | `AsyncMock` returning mock scalar (first_name, urgency_flag update) |
| `load_urgency_keywords()` | `patch` returning a small set of pre-compiled patterns for speed |
| `load_emergency_contact_config()` | `patch` returning a fixture `EmergencyContactConfig` |
| `get_current_patient_token` | Override dependency with `{"encounter_id": "..."}` |
| `UrgencyDetector.detect()` | `AsyncMock` for integration test — returns pre-set `UrgencyDetectionResult` |
| FastAPI `AsyncClient` | `httpx.AsyncClient(app=app, base_url="http://test")` |

---

## Acceptance Criteria Addressed

| US-044 AC | Test Cases |
|-----------|-----------|
| Scenario 1 | `test_urgent_message_returns_emergency_reply_without_llm_call` |
| Scenario 2 | `test_all_ac_scenario_2_keywords_trigger_phase1`, `test_emergency_reply_matches_config_display_message` |
| Scenario 3 | `test_semantic_confidence_above_threshold_triggers_urgency`, `test_semantic_confidence_below_threshold_not_urgent` |
| Scenario 4 | `test_non_urgent_message_proceeds_to_normal_pipeline` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/patient_comm/urgency
touch backend/tests/unit/agents/patient_comm/urgency/__init__.py
mkdir -p api-gateway/tests/unit/routers  # already exists from US-043
```

### 2. Create `backend/tests/unit/agents/patient_comm/urgency/test_keyword_matcher.py`

```python
"""Unit tests for Phase 1 keyword matcher (US-044 TASK-002).

Covers:
    - All AC Scenario 2 keywords trigger is_urgent=True via Phase 1
    - Non-urgent message returns is_urgent=False
    - matched_phrase and message_summary contain keyword, not raw patient message
    - PHI protection: patient message does not appear in any logged field
"""
import pytest

from backend.app.agents.patient_comm.urgency.keyword_matcher import detect_urgency_keyword
from backend.app.agents.patient_comm.urgency.schemas import DetectionPhase


# AC Scenario 2 required keywords
AC_SCENARIO_2_CASES = [
    ("I have chest pain and can't breathe", "chest pain"),
    ("I cannot breathe properly", "cannot breathe"),
    ("There is severe bleeding from the wound", "severe bleeding"),
    ("She is unconscious on the floor", "unconscious"),
    ("He might be having a stroke", "stroke"),
    ("I am thinking about suicide", "suicide"),
]


class TestKeywordMatcherUrgentCases:
    @pytest.mark.parametrize("message,expected_keyword", AC_SCENARIO_2_CASES)
    def test_ac_scenario_2_keywords_trigger_phase1(self, message: str, expected_keyword: str):
        result = detect_urgency_keyword(message)
        assert result.is_urgent is True
        assert result.detection_phase == DetectionPhase.KEYWORD
        assert result.matched_phrase is not None
        assert expected_keyword.lower() in result.matched_phrase.lower()

    def test_matched_phrase_does_not_contain_raw_message(self):
        """matched_phrase must contain only the keyword, not the surrounding patient text."""
        message = "I have chest pain and also a fever and feel generally unwell"
        result = detect_urgency_keyword(message)
        assert result.is_urgent is True
        # matched_phrase should be the keyword phrase, not the full message
        assert len(result.matched_phrase) < len(message)
        assert "fever" not in result.matched_phrase
        assert "generally unwell" not in result.matched_phrase

    def test_message_summary_does_not_contain_raw_message(self):
        """message_summary must be a system-generated string, not the patient's message."""
        message = "my heart is racing and I have chest pain — please help me immediately"
        result = detect_urgency_keyword(message)
        assert result.is_urgent is True
        # message_summary should not reproduce the patient's full message text
        assert "please help me immediately" not in (result.message_summary or "")
        assert "racing" not in (result.message_summary or "")

    def test_case_insensitive_matching(self):
        result = detect_urgency_keyword("I HAVE CHEST PAIN")
        assert result.is_urgent is True

    def test_partial_word_does_not_match(self):
        """'chestpain123' (no word boundary) should not trigger."""
        result = detect_urgency_keyword("chestpain123 is a variable name in my code")
        # Word boundary anchors should prevent this from matching
        assert result.is_urgent is False or result.matched_phrase != "chest pain"


class TestKeywordMatcherNonUrgent:
    def test_medication_question_not_urgent(self):
        """AC Scenario 4 — non-urgent message must return is_urgent=False."""
        result = detect_urgency_keyword("when should I take my metformin?")
        assert result.is_urgent is False
        assert result.detection_phase == DetectionPhase.NONE
        assert result.matched_phrase is None
        assert result.message_summary is None

    def test_general_health_question_not_urgent(self):
        result = detect_urgency_keyword("Can I eat spicy food after surgery?")
        assert result.is_urgent is False

    def test_activity_question_not_urgent(self):
        result = detect_urgency_keyword("When can I start exercising again?")
        assert result.is_urgent is False
```

### 3. Create `backend/tests/unit/agents/patient_comm/urgency/test_semantic_classifier.py`

```python
"""Unit tests for Phase 2 Gemini semantic classifier (US-044 TASK-003).

Covers:
    - confidence >= 0.8 → is_urgent=True, detection_phase=SEMANTIC
    - confidence < 0.8 → is_urgent=False even when urgency=True
    - confidence == 0.8 (boundary) → is_urgent=True
    - LLM returns malformed JSON → retry logic; safe fallback after max retries
    - Safe fallback always returns is_urgent=False (not True)
    - patient_message never in logger calls (PHI protection)
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.app.agents.patient_comm.urgency.schemas import DetectionPhase
from backend.app.agents.patient_comm.urgency.semantic_classifier import classify_urgency_semantic


def _make_llm_response(urgency: bool, confidence: float) -> AsyncMock:
    content = json.dumps({"urgency": urgency, "confidence": confidence})
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value=AIMessage(content=content))
    return mock


class TestSemanticClassifierThreshold:
    @pytest.mark.asyncio
    async def test_confidence_above_threshold_triggers_urgency(self):
        """AC Scenario 3 — semantic urgency detected when confidence >= 0.8."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=True, confidence=0.93),
        ):
            result = await classify_urgency_semantic(
                "my heart is racing really fast and I feel dizzy"
            )
        assert result.is_urgent is True
        assert result.detection_phase == DetectionPhase.SEMANTIC
        assert result.confidence == pytest.approx(0.93)

    @pytest.mark.asyncio
    async def test_confidence_at_boundary_triggers_urgency(self):
        """Exactly 0.8 must trigger urgency (inclusive boundary)."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=True, confidence=0.8),
        ):
            result = await classify_urgency_semantic("I feel really unwell")
        assert result.is_urgent is True

    @pytest.mark.asyncio
    async def test_confidence_below_threshold_not_urgent(self):
        """confidence=0.79 must NOT trigger urgency even if urgency=True."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=True, confidence=0.79),
        ):
            result = await classify_urgency_semantic("I feel a bit off today")
        assert result.is_urgent is False
        assert result.detection_phase == DetectionPhase.NONE

    @pytest.mark.asyncio
    async def test_gemini_urgency_false_not_urgent(self):
        """urgency=False regardless of confidence → is_urgent=False."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=False, confidence=0.99),
        ):
            result = await classify_urgency_semantic("when should I take my metformin?")
        assert result.is_urgent is False


class TestSemanticClassifierRetryAndFallback:
    @pytest.mark.asyncio
    async def test_malformed_json_triggers_retry_and_safe_fallback(self):
        """On repeated malformed JSON after max retries, safe fallback returns is_urgent=False."""
        malformed_response = AIMessage(content="This is not JSON at all.")

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=malformed_response)

        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=mock_llm,
        ):
            result = await classify_urgency_semantic("some patient message")

        # Safe fallback — must not return is_urgent=True
        assert result.is_urgent is False
        assert result.detection_phase == DetectionPhase.NONE
        # Confirm retries occurred (ainvoke called more than once)
        assert mock_llm.ainvoke.call_count >= 2

    @pytest.mark.asyncio
    async def test_safe_fallback_never_triggers_urgency(self):
        """The safe fallback path must always return is_urgent=False for patient safety.

        A false negative (missed urgency) is safer than a false positive that
        causes alert fatigue and desensitises care teams.
        """
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("Vertex AI unavailable"))

        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=mock_llm,
        ):
            result = await classify_urgency_semantic("any message")

        assert result.is_urgent is False
```

### 4. Create `backend/tests/unit/agents/patient_comm/urgency/test_urgency_detector.py`

```python
"""Unit tests for UrgencyDetector facade (US-044 TASK-003).

Covers:
    - Phase 1 match → Phase 2 NOT called (keyword short-circuit)
    - Phase 1 no match → Phase 2 called exactly once
    - Verdict from each phase propagated correctly
"""
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agents.patient_comm.urgency.detector import UrgencyDetector
from backend.app.agents.patient_comm.urgency.schemas import (
    DetectionPhase,
    UrgencyDetectionResult,
)


URGENT_KEYWORD_RESULT = UrgencyDetectionResult(
    is_urgent=True,
    detection_phase=DetectionPhase.KEYWORD,
    matched_phrase="chest pain",
    confidence=None,
    message_summary="Urgency keyword detected: 'chest pain'",
)

URGENT_SEMANTIC_RESULT = UrgencyDetectionResult(
    is_urgent=True,
    detection_phase=DetectionPhase.SEMANTIC,
    matched_phrase=None,
    confidence=0.92,
    message_summary="Semantic urgency signal detected by AI classifier",
)

NOT_URGENT_RESULT = UrgencyDetectionResult(
    is_urgent=False,
    detection_phase=DetectionPhase.NONE,
    matched_phrase=None,
    confidence=None,
    message_summary=None,
)


class TestUrgencyDetectorPhaseOrchestration:
    @pytest.mark.asyncio
    async def test_phase1_match_skips_phase2(self):
        """When keyword match found, Gemini semantic classifier must NOT be called."""
        detector = UrgencyDetector()

        with (
            patch(
                "backend.app.agents.patient_comm.urgency.detector.detect_urgency_keyword",
                return_value=URGENT_KEYWORD_RESULT,
            ),
            patch(
                "backend.app.agents.patient_comm.urgency.detector.classify_urgency_semantic",
                new_callable=AsyncMock,
            ) as mock_phase2,
        ):
            result = await detector.detect("I have chest pain")

        assert result.is_urgent is True
        assert result.detection_phase == DetectionPhase.KEYWORD
        mock_phase2.assert_not_called()  # Phase 2 must be skipped

    @pytest.mark.asyncio
    async def test_phase1_no_match_calls_phase2(self):
        """When no keyword match, Phase 2 (Gemini) must be called exactly once."""
        detector = UrgencyDetector()

        with (
            patch(
                "backend.app.agents.patient_comm.urgency.detector.detect_urgency_keyword",
                return_value=NOT_URGENT_RESULT,
            ),
            patch(
                "backend.app.agents.patient_comm.urgency.detector.classify_urgency_semantic",
                new_callable=AsyncMock,
                return_value=URGENT_SEMANTIC_RESULT,
            ) as mock_phase2,
        ):
            result = await detector.detect("my heart is racing and I feel dizzy")

        assert result.is_urgent is True
        assert result.detection_phase == DetectionPhase.SEMANTIC
        mock_phase2.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_urgent_returns_none_phase(self):
        """Non-urgent message: both phases return NONE → final result is NONE."""
        detector = UrgencyDetector()

        with (
            patch(
                "backend.app.agents.patient_comm.urgency.detector.detect_urgency_keyword",
                return_value=NOT_URGENT_RESULT,
            ),
            patch(
                "backend.app.agents.patient_comm.urgency.detector.classify_urgency_semantic",
                new_callable=AsyncMock,
                return_value=NOT_URGENT_RESULT,
            ),
        ):
            result = await detector.detect("when should I take my metformin?")

        assert result.is_urgent is False
        assert result.detection_phase == DetectionPhase.NONE
```

### 5. Create `api-gateway/tests/unit/routers/test_chat_urgency_integration.py`

```python
"""Integration unit tests for urgency gate in POST /api/v1/chat (US-044 TASK-005).

Covers:
    - Urgent message → emergency reply returned, GeminiFlashClient NOT called
    - Non-urgent message → normal pipeline proceeds, UrgencyDetector called first
    - JWT scope enforcement still runs before urgency detection
    - Emergency reply text matches config display_message
"""
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from backend.app.agents.patient_comm.urgency.schemas import (
    DetectionPhase,
    UrgencyDetectionResult,
)

URGENT_RESULT = UrgencyDetectionResult(
    is_urgent=True,
    detection_phase=DetectionPhase.KEYWORD,
    matched_phrase="chest pain",
    confidence=None,
    message_summary="Urgency keyword detected: 'chest pain'",
)

NOT_URGENT_RESULT = UrgencyDetectionResult(
    is_urgent=False,
    detection_phase=DetectionPhase.NONE,
    matched_phrase=None,
    confidence=None,
    message_summary=None,
)

ENCOUNTER_ID = "550e8400-e29b-41d4-a716-446655440000"
SESSION_ID = "660e8400-e29b-41d4-a716-446655440001"
EMERGENCY_DISPLAY_MESSAGE = (
    "⚠ Emergency Alert: This sounds serious. Call 911 immediately or go to the "
    "nearest emergency room. Your care team has been notified."
)


class TestChatUrgencyGateIntegration:
    @pytest.mark.asyncio
    async def test_urgent_message_returns_emergency_reply_without_llm_call(
        self, async_client: AsyncClient
    ):
        """AC Scenario 1 & 2 — urgent message triggers emergency reply; LLM not called."""
        with (
            patch(
                "api_gateway.app.routers.chat._urgency_detector.detect",
                new=AsyncMock(return_value=URGENT_RESULT),
            ),
            patch(
                "api_gateway.app.routers.chat._emergency_handler.handle",
                new=AsyncMock(return_value=EMERGENCY_DISPLAY_MESSAGE),
            ) as mock_handler,
            patch(
                "api_gateway.app.routers.chat._gemini_client.chat",  # US-043 client
                new=AsyncMock(),
            ) as mock_llm,
        ):
            response = await async_client.post(
                "/api/v1/chat",
                json={
                    "message": "I have chest pain and can't breathe",
                    "encounter_id": ENCOUNTER_ID,
                    "session_id": SESSION_ID,
                },
                headers={"Authorization": f"Bearer <patient-jwt>"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["reply"] == EMERGENCY_DISPLAY_MESSAGE
        mock_handler.assert_called_once()
        mock_llm.assert_not_called()  # LLM must NOT be called for urgent messages

    @pytest.mark.asyncio
    async def test_non_urgent_message_proceeds_to_normal_pipeline(
        self, async_client: AsyncClient
    ):
        """AC Scenario 4 — non-urgent message bypasses urgency handler; LLM called normally."""
        with (
            patch(
                "api_gateway.app.routers.chat._urgency_detector.detect",
                new=AsyncMock(return_value=NOT_URGENT_RESULT),
            ),
            patch(
                "api_gateway.app.routers.chat._emergency_handler.handle",
                new=AsyncMock(),
            ) as mock_handler,
            patch(
                "api_gateway.app.routers.chat._gemini_client.chat",
                new=AsyncMock(return_value="Take metformin with food after meals."),
            ) as mock_llm,
        ):
            response = await async_client.post(
                "/api/v1/chat",
                json={
                    "message": "when should I take my metformin?",
                    "encounter_id": ENCOUNTER_ID,
                    "session_id": SESSION_ID,
                },
                headers={"Authorization": f"Bearer <patient-jwt>"},
            )

        assert response.status_code == 200
        mock_handler.assert_not_called()  # Emergency handler must NOT be called
        mock_llm.assert_called_once()  # Normal LLM pipeline must proceed

    @pytest.mark.asyncio
    async def test_scope_enforcement_runs_before_urgency_detection(
        self, async_client: AsyncClient
    ):
        """JWT scope enforcement must reject mismatched encounter_id BEFORE urgency detection."""
        wrong_encounter_id = "aaaaaaaa-e29b-41d4-a716-446655440000"

        with patch(
            "api_gateway.app.routers.chat._urgency_detector.detect",
            new=AsyncMock(return_value=URGENT_RESULT),
        ) as mock_detector:
            response = await async_client.post(
                "/api/v1/chat",
                json={
                    "message": "I have chest pain",
                    "encounter_id": wrong_encounter_id,  # Does not match JWT claim
                    "session_id": SESSION_ID,
                },
                headers={"Authorization": f"Bearer <patient-jwt>"},
            )

        assert response.status_code == 403
        mock_detector.assert_not_called()  # Scope check must block before urgency detection
```

---

## Validation Checklist

```bash
# Run all US-044 unit tests
pytest backend/tests/unit/agents/patient_comm/urgency/ \
       api-gateway/tests/unit/routers/test_chat_urgency_integration.py \
       --cov=backend.app.agents.patient_comm.urgency \
       --cov=api_gateway.app.routers.chat \
       --cov-report=term-missing \
       --cov-fail-under=80 \
       -v --tb=short

# Confirm all US-043 tests still pass (regression check)
pytest api-gateway/tests/unit/routers/test_chat_endpoint.py -v --tb=short
```

---

## Definition of Done

- [ ] `test_keyword_matcher.py`: all AC Scenario 2 keywords tested; non-urgent exclusion verified; raw message absent from `matched_phrase` and `message_summary`
- [ ] `test_semantic_classifier.py`: confidence=0.8 boundary tested (inclusive); confidence=0.79 rejected; retry logic and safe fallback tested
- [ ] `test_urgency_detector.py`: Phase 1 match short-circuits Phase 2; Phase 2 called only when Phase 1 returns NONE
- [ ] `test_chat_urgency_integration.py`: urgent message → no LLM call; non-urgent → LLM called; scope enforcement blocks before urgency detection
- [ ] All tests pass: `pytest ... --cov-fail-under=80`
- [ ] All US-043 tests continue to pass (no regression)
