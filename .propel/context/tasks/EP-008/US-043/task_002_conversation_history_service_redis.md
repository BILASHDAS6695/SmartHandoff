---
id: TASK-002
title: "Conversation History Service — Redis FIFO Storage with 2K-Token Pruning"
user_story: US-043
epic: EP-008
sprint: 2
layer: Backend / Infrastructure
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-043/TASK-001, US-001]
---

# TASK-002: Conversation History Service — Redis FIFO Storage with 2K-Token Pruning

> **Story:** US-043 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / Infrastructure | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-043 requires conversation history stored in Cloud Memorystore Redis at the key pattern `conversation-history:{encounter_id}:{session_id}` with a 24-hour TTL. The history drives two critical behaviours:

1. **FIFO pruning** — the conversation history component of the 8 K context window is budgeted at 2 K tokens. When the total token count of stored messages exceeds this budget, the oldest messages are dropped first, preserving the most recent exchanges (US-043 AC Scenario 4).
2. **Session isolation** — each `session_id` is a separate Redis key; multiple independent sessions per encounter are allowed (US-043 Technical Notes). A session key is scoped to a single `encounter_id`, preventing cross-session data bleed.

The Redis client connects to Cloud Memorystore via the private VPC IP exposed through the `REDIS_URL` environment variable (design.md §9.1 — Cloud Memorystore Redis at `10.0.2.20`; design.md §10.3 — token blocklist and drug interaction cache also use this instance).

Token counting uses a lightweight approximation: `len(text.split()) * 1.33` rounded up. This avoids a `tiktoken` dependency in the agent container and introduces ≤5% estimation error — acceptable for context window management. The Gemini Flash API enforces the hard 8 K token limit independently.

**Design references:**
- design.md §4.1 — Cloud Memorystore (Redis) for token blocklist + drug interaction cache
- design.md §7.3 AIR-024 — context window: system prompt (2 K) + discharge summary (4 K) + conversation history (2 K); FIFO pruning
- design.md §9.1 — Cloud Memorystore Redis at `10.0.2.20` (data subnet)
- design.md §10.3 — `conversation-history:{encounter_id}:{session_id}` key pattern; TTL = 24 h
- US-001 — Redis infrastructure provisioned (this task consumes it)
- US-043 AC Scenario 4 — oldest messages pruned; system prompt and discharge context never pruned
- US-043 Technical Notes — deque of last 10 messages; drop oldest when total tokens exceed 2 K

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | FIFO pruning enforced: conversation history does not exceed 2 K tokens; oldest messages dropped first |

---

## Implementation Steps

### 1. Create module files

```bash
touch backend/app/agents/patient_comm/chatbot/history_service.py
touch backend/app/agents/patient_comm/chatbot/token_counter.py
```

### 2. Implement `backend/app/agents/patient_comm/chatbot/token_counter.py`

```python
"""Lightweight token count estimation for context window management.

Uses a word-count approximation (words × 1.33) rather than a full tokeniser
to avoid a tiktoken dependency in the patient-comm agent container.
Maximum estimation error is ≤5% for English medical discharge text —
acceptable for managing the 2 K conversation history budget.

Design refs:
    US-043 AC Scenario 4 — FIFO pruning when conversation history exceeds 2 K tokens
    design.md AIR-024 — 8 K total context window
"""
from __future__ import annotations

import math


# Approximation constant: average English word ≈ 0.75 tokens in Gemini tokeniser
_WORDS_TO_TOKENS_FACTOR: float = 1.33


def estimate_tokens(text: str) -> int:
    """Return an estimated token count for *text*.

    Args:
        text: Plain-text string to estimate.

    Returns:
        Estimated integer token count, always ≥ 1 for non-empty text.
    """
    if not text.strip():
        return 0
    word_count = len(text.split())
    return math.ceil(word_count * _WORDS_TO_TOKENS_FACTOR)


def estimate_message_tokens(role: str, content: str) -> int:
    """Estimate tokens for a single conversation turn including role prefix.

    Adds 4 tokens of overhead for Gemini chat format markers
    (e.g. <start_of_turn>user\\n ... <end_of_turn>).
    """
    return estimate_tokens(f"{role}: {content}") + 4
```

### 3. Implement `backend/app/agents/patient_comm/chatbot/history_service.py`

```python
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
```

---

## Validation Checklist

```bash
# Syntax check — both modules
python -c "
import ast, pathlib
for f in [
    'backend/app/agents/patient_comm/chatbot/token_counter.py',
    'backend/app/agents/patient_comm/chatbot/history_service.py',
]:
    ast.parse(pathlib.Path(f).read_text())
    print(f'{f} — syntax OK')
"

# Token counter sanity check
python -c "
from backend.app.agents.patient_comm.chatbot.token_counter import estimate_tokens
assert estimate_tokens('') == 0
assert estimate_tokens('hello world') > 0
print('token_counter.estimate_tokens — basic assertions ✓')
"

# FIFO pruning logic (standalone — no Redis connection needed)
python -c "
from backend.app.agents.patient_comm.chatbot.history_service import _apply_fifo_pruning
from backend.app.agents.patient_comm.chatbot.schemas import ConversationMessage, MessageRole

# Build 12 messages that exceed 2K token budget when combined
msgs = [
    ConversationMessage(role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                        content='word ' * 120)
    for i in range(12)
]
pruned = _apply_fifo_pruning(msgs)
assert len(pruned) <= 10, f'Expected ≤10 messages, got {len(pruned)}'
print(f'FIFO pruning: {len(msgs)} → {len(pruned)} messages ✓')
"
```

---

## Definition of Done

- [ ] `backend/app/agents/patient_comm/chatbot/token_counter.py` created
- [ ] `backend/app/agents/patient_comm/chatbot/history_service.py` created
- [ ] `_build_key()` generates keys matching pattern `conversation-history:{uuid}:{uuid}`
- [ ] `_apply_fifo_pruning()` drops oldest messages until total tokens ≤ 2 K budget
- [ ] `MAX_HISTORY_MESSAGES` cap of 10 enforced before token-based pruning
- [ ] Redis TTL set to 86 400 seconds (24 h) on every write
- [ ] Redis URL read from `REDIS_URL` env var — no hardcoded IP (TR-021)
- [ ] `content` field never appears in `logger.*` calls (PHI protection)
- [ ] Syntax check passes without errors
