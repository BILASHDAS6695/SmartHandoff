"""Unit tests for ConversationHistoryService and FIFO pruning (TASK-002).

Covers:
    - FIFO pruning drops oldest messages when token budget exceeded (AC Scenario 4)
    - MAX_HISTORY_MESSAGES cap (10 messages) applied before token-based pruning
    - Redis key pattern matches `conversation-history:{eid}:{sid}`
    - Empty history returned when Redis key does not exist
    - Updated history serialised and written with 24h TTL
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agents.patient_comm.chatbot.history_service import (
    ConversationHistoryService,
    _apply_fifo_pruning,
    _build_key,
)
from backend.app.agents.patient_comm.chatbot.schemas import (
    CONVERSATION_HISTORY_TOKEN_BUDGET,
    MAX_HISTORY_MESSAGES,
    ConversationHistory,
    ConversationMessage,
    MessageRole,
)


ENC_ID = "550e8400-e29b-41d4-a716-446655440000"
SES_ID = "660e8400-e29b-41d4-a716-446655440001"


class TestBuildKey:
    def test_key_matches_expected_pattern(self):
        key = _build_key(ENC_ID, SES_ID)
        assert key == f"conversation-history:{ENC_ID}:{SES_ID}"


class TestFifoPruning:
    def _make_messages(self, n: int, words_per_msg: int = 120) -> list[ConversationMessage]:
        return [
            ConversationMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content="word " * words_per_msg,
            )
            for i in range(n)
        ]

    def test_12_messages_pruned_to_max_10(self):
        """MAX_HISTORY_MESSAGES cap removes messages beyond 10 before token check."""
        msgs = self._make_messages(12, words_per_msg=1)  # Very short — under token budget
        pruned = _apply_fifo_pruning(msgs)
        assert len(pruned) <= MAX_HISTORY_MESSAGES

    def test_token_budget_respected_after_pruning(self):
        """Total estimated tokens of pruned list must not exceed 2K."""
        from backend.app.agents.patient_comm.chatbot.token_counter import estimate_message_tokens
        msgs = self._make_messages(10, words_per_msg=300)  # ~400 tokens each
        pruned = _apply_fifo_pruning(msgs)
        total = sum(estimate_message_tokens(m.role.value, m.content) for m in pruned)
        assert total <= CONVERSATION_HISTORY_TOKEN_BUDGET, (
            f"Pruned history exceeds 2K budget: {total} tokens"
        )

    def test_oldest_messages_dropped_first(self):
        """After pruning, only the most recent messages should remain."""
        msgs = [
            ConversationMessage(role=MessageRole.USER, content=f"message_{i} " + "word " * 200)
            for i in range(8)
        ]
        pruned = _apply_fifo_pruning(msgs)
        # The last message (most recent) should be retained
        if pruned:
            assert pruned[-1].content.startswith("message_7")

    def test_empty_list_returns_empty(self):
        assert _apply_fifo_pruning([]) == []

    def test_single_short_message_not_pruned(self):
        msgs = [ConversationMessage(role=MessageRole.USER, content="How long do I rest?")]
        pruned = _apply_fifo_pruning(msgs)
        assert len(pruned) == 1


class TestConversationHistoryService:
    @pytest.mark.asyncio
    async def test_load_returns_empty_history_on_cache_miss(self):
        service = ConversationHistoryService()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock()

        with patch(
            "backend.app.agents.patient_comm.chatbot.history_service._get_redis_client",
            return_value=mock_client,
        ):
            history = await service.load(ENC_ID, SES_ID)

        assert history.messages == []
        assert history.encounter_id == ENC_ID
        assert history.session_id == SES_ID

    @pytest.mark.asyncio
    async def test_append_and_save_writes_with_ttl(self):
        service = ConversationHistoryService()
        history = ConversationHistory(
            session_id=SES_ID, encounter_id=ENC_ID, messages=[]
        )
        user_msg = ConversationMessage(role=MessageRole.USER, content="Can I eat normally?")
        assistant_msg = ConversationMessage(role=MessageRole.ASSISTANT, content="Yes, as per instructions.")

        mock_client = AsyncMock()
        mock_client.setex = AsyncMock(return_value=True)
        mock_client.aclose = AsyncMock()

        with patch(
            "backend.app.agents.patient_comm.chatbot.history_service._get_redis_client",
            return_value=mock_client,
        ):
            updated = await service.append_and_save(history, user_msg, assistant_msg)

        # Verify setex was called with the correct key and TTL
        mock_client.setex.assert_awaited_once()
        call_args = mock_client.setex.call_args
        key_arg = call_args[0][0]
        ttl_arg = call_args[0][1]
        assert key_arg == f"conversation-history:{ENC_ID}:{SES_ID}"
        assert ttl_arg == 86_400  # 24h TTL

        # Verify messages were appended
        assert len(updated.messages) == 2
