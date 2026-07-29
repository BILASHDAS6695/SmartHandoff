"""Unit tests for Phase 2 semantic classifier (US-044 TASK-003).

Covers:
    - Gemini confidence threshold at/below 0.8
    - Retry logic on malformed JSON
    - Safe fallback on repeated failures (never triggers urgency on LLM error)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.app.agents.patient_comm.urgency.semantic_classifier import (
    classify_urgency_semantic,
)
from backend.app.agents.patient_comm.urgency.schemas import (
    DetectionPhase,
    GeminiUrgencyClassification,
)


def _make_llm_response(urgency: bool, confidence: float) -> MagicMock:
    """Create a mock ChatVertexAI that returns a given Gemini response."""
    response = AIMessage(
        content=f'{{"urgency": {str(urgency).lower()}, "confidence": {confidence}}}'
    )
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=response)
    return mock_llm


class TestSemanticClassifierConfidenceThreshold:
    @pytest.mark.asyncio
    async def test_high_confidence_urgency_triggers(self):
        """High confidence (0.93) with urgency=True must trigger is_urgent=True."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=True, confidence=0.93),
        ):
            result = await classify_urgency_semantic("my heart is racing really fast")
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
        assert result.detection_phase == DetectionPhase.SEMANTIC

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
            result = await classify_urgency_semantic(
                "when should I take my metformin?"
            )
        assert result.is_urgent is False

    @pytest.mark.asyncio
    async def test_low_confidence_false_urgency_not_urgent(self):
        """urgency=False with low confidence → is_urgent=False."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=False, confidence=0.2),
        ):
            result = await classify_urgency_semantic("I have a question")
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
    async def test_safe_fallback_never_triggers_urgency_on_exception(self):
        """The safe fallback path must always return is_urgent=False on exception.

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
        assert result.detection_phase == DetectionPhase.NONE

    @pytest.mark.asyncio
    async def test_validation_error_triggers_safe_fallback(self):
        """Validation error on GeminiUrgencyClassification should trigger safe fallback."""
        # Return JSON that doesn't match the schema (e.g., missing confidence)
        invalid_response = AIMessage(content='{"urgency": true}')

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=invalid_response)

        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=mock_llm,
        ):
            result = await classify_urgency_semantic("patient message")

        assert result.is_urgent is False

    @pytest.mark.asyncio
    async def test_successful_parse_on_second_attempt(self):
        """Retry logic should recover from one failure and succeed on second attempt."""
        first_response = AIMessage(content="malformed")
        second_response = AIMessage(
            content='{"urgency": true, "confidence": 0.85}'
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[first_response, second_response])

        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=mock_llm,
        ):
            result = await classify_urgency_semantic("patient message")

        # Should recover and detect urgency
        assert result.is_urgent is True
        assert mock_llm.ainvoke.call_count == 2


class TestSemanticClassifierMessageSummary:
    @pytest.mark.asyncio
    async def test_urgent_message_summary_populated(self):
        """Urgent result should have non-PHI message_summary."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=True, confidence=0.9),
        ):
            result = await classify_urgency_semantic("any message")
        assert result.message_summary is not None
        assert len(result.message_summary) > 0

    @pytest.mark.asyncio
    async def test_non_urgent_message_summary_empty(self):
        """Non-urgent result should have None message_summary."""
        with patch(
            "backend.app.agents.patient_comm.urgency.semantic_classifier.ChatVertexAI",
            return_value=_make_llm_response(urgency=False, confidence=0.1),
        ):
            result = await classify_urgency_semantic("any message")
        assert result.message_summary is None
