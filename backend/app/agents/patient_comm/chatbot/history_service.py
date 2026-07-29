"""Redis-backed conversation history service for the patient chatbot (US-043).

Responsibility:
    - Load conversation history from Redis for a given (encounter_id, session_id) pair.
    - Append a new message pair (user turn + assistant turn) to the history.
    - Apply FIFO pruning so the serialised history does not exceed
      CONVERSATION_HISTORY_TOKEN_BUDGET (2 K tokens).
    - Persist the updated history back to Redis with a 24-hour TTL.

Key pattern:
    conversation-history:{encounter_id}:{session_id}

Security:
    - Both `encounter_id` and `session_id` are UUID-validated by the schema layer
      (TASK-001 ChatRequest.validate_uuid) before reaching this service.
    - No PHI is stored in Redis — only role, content, and UTC timestamp.
    - The `content` field may contain patient health context derived from discharge
      instructions; it is therefore subject to the same PHI protection obligations
      as DB fields (DR-016, BR-020).

Design refs:
    design.md §10.3 — Cloud Memorystore Redis; key: conversation-history:{eid}:{sid}; TTL=24h
    design.md §7.3 AIR-024 — FIFO pruning; conversation history ≤ 2 K tokens
    US-043 AC Scenario 4 — oldest messages pruned; system prompt + discharge context preserved
    US-043 Technical Notes — deque of last 10 messages
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from datetime import datetime, timezone

import redis.asyncio as aioredis

from backend.app.agents.patient_comm.chatbot.schemas import (
    CONVERSATION_HISTORY_TOKEN_BUDGET,
    MAX_HISTORY_MESSAGES,
    ConversationHistory,
    ConversationMessage,
    MessageRole,
)
from backend.app.agents.patient_comm.chatbot.token_counter import estimate_message_tokens

logger = logging.getLogger(__name__)

# Redis TTL for conversation history keys — 24 hours (US-043 DoD)
_HISTORY_TTL_SECONDS: int = 86_400

# Key prefix — defines the Redis key namespace for chat history
_KEY_PREFIX: str = "conversation-history"


def _build_key(encounter_id: str, session_id: str) -> str:
    """Construct the Redis key for a conversation session.

    Key pattern: conversation-history:{encounter_id}:{session_id}
    Both UUIDs are pre-validated by ChatRequest.validate_uuid before this is called.
    """
    return f"{_KEY_PREFIX}:{encounter_id}:{session_id}"


def _get_redis_client() -> aioredis.Redis:
    """Return an async Redis client connected to Cloud Memorystore.

    Connection URL is injected via REDIS_URL environment variable
    (design.md §9.1 — private VPC IP; TR-021 — no hardcoded credentials).
    """
    redis_url = os.environ["REDIS_URL"]  # e.g. redis://10.0.2.20:6379/0
    return aioredis.from_url(redis_url, decode_responses=True)


def _serialise_history(history: ConversationHistory) -> str:
    """Serialise a ConversationHistory to a JSON string for Redis storage."""
    return json.dumps(
        {
            "session_id": history.session_id,
            "encounter_id": history.encounter_id,
            "messages": [
                {
                    "role": msg.role.value,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in history.messages
            ],
        }
    )


def _deserialise_history(raw: str, encounter_id: str, session_id: str) -> ConversationHistory:
    """Deserialise a JSON string from Redis back to a ConversationHistory."""
    data = json.loads(raw)
    messages = [
        ConversationMessage(
            role=MessageRole(m["role"]),
            content=m["content"],
            timestamp=datetime.fromisoformat(m["timestamp"]),
        )
        for m in data.get("messages", [])
    ]
    return ConversationHistory(
        session_id=session_id,
        encounter_id=encounter_id,
        messages=messages,
    )


def _apply_fifo_pruning(messages: list[ConversationMessage]) -> list[ConversationMessage]:
    """Drop the oldest messages until the list fits within CONVERSATION_HISTORY_TOKEN_BUDGET.

    Algorithm (US-043 Technical Notes):
        1. Maintain a deque of at most MAX_HISTORY_MESSAGES (10) messages.
        2. Sum estimated tokens across all messages.
        3. While total tokens > CONVERSATION_HISTORY_TOKEN_BUDGET (2 K),
           pop from the left (oldest message first).

    The system prompt and discharge summary are managed separately by
    ContextAssembler (TASK-003) and are NEVER affected by this pruning.
    """
    message_deque: deque[ConversationMessage] = deque(messages, maxlen=MAX_HISTORY_MESSAGES)

    total_tokens = sum(
        estimate_message_tokens(msg.role.value, msg.content) for msg in message_deque
    )

    while total_tokens > CONVERSATION_HISTORY_TOKEN_BUDGET and message_deque:
        removed = message_deque.popleft()
        removed_tokens = estimate_message_tokens(removed.role.value, removed.content)
        total_tokens -= removed_tokens
        logger.debug(
            "FIFO pruning: removed oldest message; tokens_removed=%d; tokens_remaining=%d",
            removed_tokens,
            total_tokens,
        )

    return list(message_deque)


class ConversationHistoryService:
    """Async service for loading, appending, and persisting chatbot conversation history.

    Usage (inside an async context):
        service = ConversationHistoryService()
        history = await service.load(encounter_id, session_id)
        history = await service.append_and_save(
            history,
            user_message=user_turn,
            assistant_message=assistant_turn,
        )
    """

    async def load(self, encounter_id: str, session_id: str) -> ConversationHistory:
        """Load the conversation history for a session from Redis.

        Returns an empty ConversationHistory if no key exists (first message in session).
        """
        client = _get_redis_client()
        try:
            raw = await client.get(_build_key(encounter_id, session_id))
            if raw is None:
                logger.debug(
                    "No existing history for session; returning empty history "
                    "encounter_id=%s session_id=%s",
                    encounter_id,
                    session_id,
                )
                return ConversationHistory(
                    session_id=session_id,
                    encounter_id=encounter_id,
                    messages=[],
                )
            return _deserialise_history(raw, encounter_id, session_id)
        finally:
            await client.aclose()

    async def append_and_save(
        self,
        history: ConversationHistory,
        user_message: ConversationMessage,
        assistant_message: ConversationMessage,
    ) -> ConversationHistory:
        """Append a user/assistant turn pair, apply FIFO pruning, and persist to Redis.

        Both messages are appended atomically (user first, then assistant).
        FIFO pruning is applied after appending to respect the 2 K token budget.
        The updated history is written back to Redis with a refreshed 24-hour TTL.
        """
        updated_messages = [*history.messages, user_message, assistant_message]
        pruned_messages = _apply_fifo_pruning(updated_messages)

        updated_history = ConversationHistory(
            session_id=history.session_id,
            encounter_id=history.encounter_id,
            messages=pruned_messages,
        )

        client = _get_redis_client()
        try:
            key = _build_key(history.encounter_id, history.session_id)
            await client.setex(key, _HISTORY_TTL_SECONDS, _serialise_history(updated_history))
            logger.debug(
                "Saved conversation history; encounter_id=%s session_id=%s messages=%d",
                history.encounter_id,
                history.session_id,
                len(pruned_messages),
            )
        finally:
            await client.aclose()

        return updated_history
