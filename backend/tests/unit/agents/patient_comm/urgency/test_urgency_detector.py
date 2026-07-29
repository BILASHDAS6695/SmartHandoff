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

    @pytest.mark.asyncio
    async def test_phase2_urgent_result_propagated(self):
        """Phase 2 urgency result should be propagated correctly."""
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
            ),
        ):
            result = await detector.detect("some ambiguous message")

        assert result.is_urgent is True
        assert result.detection_phase == DetectionPhase.SEMANTIC
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_phase1_urgent_all_fields_present(self):
        """Phase 1 urgent result must have matched_phrase and message_summary."""
        detector = UrgencyDetector()

        with (
            patch(
                "backend.app.agents.patient_comm.urgency.detector.detect_urgency_keyword",
                return_value=URGENT_KEYWORD_RESULT,
            ),
            patch(
                "backend.app.agents.patient_comm.urgency.detector.classify_urgency_semantic",
                new_callable=AsyncMock,
            ),
        ):
            result = await detector.detect("I have chest pain")

        assert result.matched_phrase is not None
        assert result.message_summary is not None
        assert result.confidence is None  # Phase 1 has no confidence score
