"""Unit tests for US-043 Pydantic schemas (TASK-001).

Covers:
    - ChatRequest UUID validation rejects non-UUIDs
    - ChatAuditEvent contains no PHI fields (message, patient name)
    - GenerationType enum values
"""
import pytest
from pydantic import ValidationError

from backend.app.agents.patient_comm.chatbot.schemas import (
    ChatAuditEvent,
    ChatRequest,
    GenerationType,
    TOTAL_CONTEXT_TOKEN_BUDGET,
)


class TestChatRequestValidation:
    def test_valid_request_accepted(self):
        req = ChatRequest(
            message="What are my medication instructions?",
            encounter_id="550e8400-e29b-41d4-a716-446655440000",
            session_id="660e8400-e29b-41d4-a716-446655440001",
        )
        assert req.encounter_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_non_uuid_encounter_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(
                message="test",
                encounter_id="not-a-valid-uuid",
                session_id="660e8400-e29b-41d4-a716-446655440001",
            )
        assert "encounter_id" in str(exc_info.value)

    def test_non_uuid_session_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(
                message="test",
                encounter_id="550e8400-e29b-41d4-a716-446655440000",
                session_id="injection-attempt'; DROP TABLE patients;--",
            )
        assert "session_id" in str(exc_info.value)

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                message="",
                encounter_id="550e8400-e29b-41d4-a716-446655440000",
                session_id="660e8400-e29b-41d4-a716-446655440001",
            )


class TestChatAuditEvent:
    def test_audit_event_has_no_message_field(self):
        """ChatAuditEvent schema must not contain message content — PHI protection."""
        from backend.app.agents.patient_comm.chatbot.schemas import ChatAuditEvent
        fields = ChatAuditEvent.model_fields.keys()
        assert "message" not in fields, "ChatAuditEvent must not contain message content"
        assert "content" not in fields

    def test_total_context_token_budget_is_8000(self):
        assert TOTAL_CONTEXT_TOKEN_BUDGET == 8_000


class TestGenerationType:
    def test_llm_and_fallback_values(self):
        assert GenerationType.LLM == "LLM"
        assert GenerationType.FALLBACK == "FALLBACK"
