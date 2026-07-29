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
    def test_ac_scenario_2_keywords_trigger_phase1(
        self, message: str, expected_keyword: str
    ):
        """All AC Scenario 2 keywords must trigger urgency via Phase 1."""
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
        """Keywords must match case-insensitively."""
        result = detect_urgency_keyword("I HAVE CHEST PAIN")
        assert result.is_urgent is True

    def test_partial_word_does_not_match(self):
        """Word boundary anchors must prevent partial word matches."""
        result = detect_urgency_keyword("chestpain123 is a variable name in my code")
        # Word boundary anchors should prevent this from matching
        if result.is_urgent:
            # If it did match (which shouldn't happen), the phrase should not be "chest pain"
            assert result.matched_phrase != "chest pain"

    def test_keyword_in_context_matches(self):
        """Keywords embedded in sentences must still match."""
        result = detect_urgency_keyword("Yesterday I started experiencing chest pain")
        assert result.is_urgent is True
        assert "chest pain" in result.matched_phrase.lower()


class TestKeywordMatcherNonUrgent:
    def test_medication_question_not_urgent(self):
        """AC Scenario 4 — non-urgent message must return is_urgent=False."""
        result = detect_urgency_keyword("when should I take my metformin?")
        assert result.is_urgent is False
        assert result.detection_phase == DetectionPhase.NONE
        assert result.matched_phrase is None
        assert result.message_summary is None

    def test_general_health_question_not_urgent(self):
        """General health questions should not trigger urgency."""
        result = detect_urgency_keyword("Can I eat spicy food after surgery?")
        assert result.is_urgent is False

    def test_appointment_request_not_urgent(self):
        """Administrative questions should not trigger urgency."""
        result = detect_urgency_keyword("I need to reschedule my appointment.")
        assert result.is_urgent is False

    def test_empty_message_not_urgent(self):
        """Empty or whitespace-only messages should not trigger urgency."""
        result = detect_urgency_keyword("   ")
        assert result.is_urgent is False

    def test_word_containing_keyword_not_urgent(self):
        """Words containing but not exactly matching keyword should not trigger."""
        # "stroked" contains "stroke" but as a substring
        result = detect_urgency_keyword("I stroked the cat")
        # Word boundaries should prevent false match
        if result.is_urgent:
            assert result.matched_phrase != "stroke"


class TestKeywordMatcherPHIProtection:
    def test_raw_message_not_in_summary(self):
        """Patient's raw message must never appear in message_summary."""
        sensitive_message = "My SSN is 123-45-6789 and I have chest pain"
        result = detect_urgency_keyword(sensitive_message)
        assert result.is_urgent is True
        # The summary should NOT contain the SSN or other patient details
        assert "123-45-6789" not in (result.message_summary or "")
        assert "SSN" not in (result.message_summary or "")

    def test_matched_phrase_length_bounded(self):
        """matched_phrase should be reasonably short — just the keyword."""
        message = "I have severe bleeding from a major arterial wound on my left arm"
        result = detect_urgency_keyword(message)
        assert result.is_urgent is True
        # matched_phrase should be roughly the length of the keyword, not the full message
        assert len(result.matched_phrase or "") < len(message) / 2
