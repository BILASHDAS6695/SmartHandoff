"""Unit tests for ContextAssembler and GeminiFlashClient (TASK-003).

Covers:
    - System prompt contains scope restriction text (AC Scenario 2)
    - Discharge summary truncated to 4K token budget
    - History messages serialised to LangChain format
    - Gemini timeout returns FALLBACK (AC Scenario 1)
    - Gemini success returns LLM generation type
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.app.agents.patient_comm.chatbot.context_assembler import (
    ContextAssembler,
    _SYSTEM_PROMPT_TEMPLATE,
    _truncate_to_token_budget,
)
from backend.app.agents.patient_comm.chatbot.gemini_client import GeminiFlashClient
from backend.app.agents.patient_comm.chatbot.schemas import (
    DISCHARGE_SUMMARY_TOKEN_BUDGET,
    ConversationHistory,
    ConversationMessage,
    GenerationType,
    MessageRole,
)
from backend.app.agents.patient_comm.chatbot.token_counter import estimate_tokens


ENC_ID = "550e8400-e29b-41d4-a716-446655440000"
SES_ID = "660e8400-e29b-41d4-a716-446655440001"


class TestTruncateToTokenBudget:
    def test_short_text_not_truncated(self):
        text = "Take your medication twice daily."
        result = _truncate_to_token_budget(text, 4_000)
        assert result == text

    def test_long_text_truncated_to_budget(self):
        long_text = "word " * 5_000  # ~6 650 tokens
        result = _truncate_to_token_budget(long_text, DISCHARGE_SUMMARY_TOKEN_BUDGET)
        assert estimate_tokens(result) <= DISCHARGE_SUMMARY_TOKEN_BUDGET

    def test_truncated_text_contains_notice(self):
        long_text = "word " * 5_000
        result = _truncate_to_token_budget(long_text, DISCHARGE_SUMMARY_TOKEN_BUDGET)
        assert "truncated" in result


class TestContextAssembler:
    def _make_history(self, messages=None) -> ConversationHistory:
        return ConversationHistory(
            session_id=SES_ID,
            encounter_id=ENC_ID,
            messages=messages or [],
        )

    def test_assemble_returns_system_plus_human_for_empty_history(self):
        assembler = ContextAssembler()
        history = self._make_history()
        messages = assembler.assemble("How long do I rest?", "Rest for 2 weeks.", history)
        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[-1], HumanMessage)

    def test_system_prompt_contains_scope_restriction(self):
        """AC Scenario 2: system prompt must restrict LLM to discharge instructions only."""
        assembler = ContextAssembler()
        history = self._make_history()
        messages = assembler.assemble("test question", "some discharge text", history)
        system_content = messages[0].content
        assert "ONLY answer questions based on the discharge instructions" in system_content

    def test_system_prompt_contains_dont_know_instruction(self):
        """AC Scenario 2: system prompt must include 'I don't know' fallback instruction."""
        assembler = ContextAssembler()
        history = self._make_history()
        messages = assembler.assemble("test", "some discharge text", history)
        assert "I don't know" in messages[0].content or "don't know" in messages[0].content

    def test_history_messages_included_in_order(self):
        assembler = ContextAssembler()
        history = self._make_history([
            ConversationMessage(role=MessageRole.USER, content="First question"),
            ConversationMessage(role=MessageRole.ASSISTANT, content="First answer"),
        ])
        messages = assembler.assemble("Second question", "discharge", history)
        # [SystemMessage, HumanMessage("First question"), AIMessage("First answer"), HumanMessage("Second question")]
        assert len(messages) == 4


class TestGeminiFlashClient:
    @pytest.mark.asyncio
    async def test_timeout_returns_fallback(self):
        """AC Scenario 1: timeout returns FALLBACK generation type without raising."""
        client = GeminiFlashClient()
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch(
            "backend.app.agents.patient_comm.chatbot.gemini_client._build_llm",
            return_value=mock_llm,
        ):
            reply, gen_type, tokens = await client.complete(
                messages=[],
                encounter_id=ENC_ID,
                session_id=SES_ID,
            )

        assert gen_type == GenerationType.FALLBACK
        assert tokens is None
        assert reply != ""  # Should contain fallback message

    @pytest.mark.asyncio
    async def test_success_returns_llm_type(self):
        """Successful Gemini call returns LLM generation type."""
        client = GeminiFlashClient()
        
        mock_response = AIMessage(
            content="Take your medication twice daily.",
            response_metadata={"usage_metadata": {"total_token_count": 42}},
        )
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "backend.app.agents.patient_comm.chatbot.gemini_client._build_llm",
            return_value=mock_llm,
        ):
            reply, gen_type, tokens = await client.complete(
                messages=[],
                encounter_id=ENC_ID,
                session_id=SES_ID,
            )

        assert gen_type == GenerationType.LLM
        assert tokens == 42
        assert reply == "Take your medication twice daily."
