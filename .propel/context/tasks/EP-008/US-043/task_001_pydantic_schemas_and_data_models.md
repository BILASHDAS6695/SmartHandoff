---
id: TASK-001
title: "Pydantic Schemas & Data Models — ChatRequest, ChatResponse, ConversationMessage"
user_story: US-043
epic: EP-008
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-043]
---

# TASK-001: Pydantic Schemas & Data Models — ChatRequest, ChatResponse, ConversationMessage

> **Story:** US-043 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-043 requires a `POST /api/v1/chat` endpoint that accepts a `{message, encounter_id, session_id}` payload, assembles an 8 K-token context window, and returns a scoped LLM response within 3 seconds. This task defines all Pydantic schemas and domain models consumed by every subsequent task in the story.

### Schemas required

| Schema | Direction | Description |
|--------|-----------|-------------|
| `ChatRequest` | Inbound | `{message, encounter_id, session_id}` from the patient portal Angular client |
| `ChatResponse` | Outbound | `{reply, session_id, encounter_id, generation_type, tokens_used}` |
| `ConversationMessage` | Domain | `{role, content, timestamp}` — a single turn stored in Redis |
| `ConversationHistory` | Domain | List of `ConversationMessage`; contains FIFO pruning metadata |
| `ChatAuditEvent` | Audit | `{encounter_id, session_id, message_timestamp}` — no PHI content logged |

**Design references:**
- design.md §3.1 — Patient Communication Agent: chatbot, urgency detection, escalation routing
- design.md §4.1 TR-006 — Chatbot response <3 seconds; Gemini Flash; context window 8 K tokens
- design.md §7.3 AIR-020 — Vertex AI JSON output mode with Pydantic schema validation
- design.md §8.2 — Patient JWT is encounter-scoped; `encounter_id` claim must match request
- US-043 AC Scenario 2 — system prompt explicitly restricts LLM to patient's own discharge instructions
- US-043 AC Scenario 4 — context window: system prompt (2 K) + discharge summary (4 K) + history (2 K)
- US-043 Technical Notes — `generation_type: FALLBACK` when timeout fallback is used

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `ChatRequest` / `ChatResponse` schema defines the `POST /api/v1/chat` contract |
| Scenario 2 | `ChatResponse.generation_type` distinguishes `LLM` from `FALLBACK` |
| Scenario 4 | `ConversationHistory` model enforces 2 K token budget with FIFO pruning metadata |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/patient_comm/chatbot
touch backend/app/agents/patient_comm/__init__.py
touch backend/app/agents/patient_comm/chatbot/__init__.py
touch backend/app/agents/patient_comm/chatbot/schemas.py
```

### 2. Implement `backend/app/agents/patient_comm/chatbot/schemas.py`

```python
"""Pydantic schemas and domain models for the AI Chatbot (US-043).

All schemas are consumed by:
    - task_004: POST /api/v1/chat FastAPI endpoint
    - task_002: ConversationHistoryService (Redis persistence)
    - task_003: ContextAssembler + GeminiFlashClient

Design refs:
    US-043 AC Scenarios 1, 2, 4
    design.md §4.1 TR-006 — 8 K token context window budget
    design.md §7.3 AIR-020 — Pydantic schema validation on LLM output
    design.md §8.2 — patient JWT encounter scope enforcement
"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MessageRole(str, Enum):
    """Role of a participant in the chatbot conversation."""

    USER = "user"
    ASSISTANT = "assistant"


class GenerationType(str, Enum):
    """Indicates whether the response was produced by the LLM or by the fallback template.

    US-043 Technical Notes: fallback flagged as FALLBACK in response metadata.
    """

    LLM = "LLM"
    FALLBACK = "FALLBACK"


# ---------------------------------------------------------------------------
# Inbound request schema
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Payload accepted by POST /api/v1/chat.

    Security note (US-043 AC Scenario 3):
        The API layer must verify that `encounter_id` matches the `encounter_id`
        claim in the patient JWT before any DB or LLM call is made.
        A mismatch MUST return HTTP 403 — no data is returned for any other encounter.
    """

    message: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description="Patient's natural-language question",
        ),
    ]
    encounter_id: Annotated[
        str,
        Field(description="UUID of the patient's encounter — must match JWT claim"),
    ]
    session_id: Annotated[
        str,
        Field(
            description=(
                "Client-generated session UUID (not the patient ID). "
                "Allows multiple chat sessions per encounter."
            )
        ),
    ]

    @field_validator("encounter_id", "session_id")
    @classmethod
    def validate_uuid(cls, value: str, info) -> str:
        """Reject non-UUID values to prevent key-injection attacks on Redis."""
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError(f"{info.field_name} must be a valid UUID v4") from exc
        return value


# ---------------------------------------------------------------------------
# Outbound response schema
# ---------------------------------------------------------------------------

class ChatResponse(BaseModel):
    """Response returned by POST /api/v1/chat.

    `generation_type` distinguishes LLM responses from timeout fallbacks
    so the Angular client can surface an appropriate UX indicator.
    """

    reply: str = Field(..., description="Assistant reply text shown to the patient")
    session_id: str = Field(..., description="Echoed from ChatRequest.session_id")
    encounter_id: str = Field(..., description="Echoed from ChatRequest.encounter_id")
    generation_type: GenerationType = Field(
        ...,
        description="LLM = Gemini Flash; FALLBACK = timeout fallback template",
    )
    tokens_used: int | None = Field(
        default=None,
        description="Total tokens consumed by the Gemini call (None for FALLBACK responses)",
    )


# ---------------------------------------------------------------------------
# Conversation message & history domain models
# ---------------------------------------------------------------------------

class ConversationMessage(BaseModel):
    """A single turn stored in the Redis conversation history.

    Audit note (US-043 Technical Notes):
        Only `timestamp` and role metadata are logged.
        The `content` field MUST NOT appear in Cloud Logging output — it may
        contain patient health information derived from discharge instructions.
    """

    role: MessageRole
    content: str = Field(..., description="Message text — excluded from all log output")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of this turn",
    )

    model_config = {"frozen": True}


# Token budget constants — US-043 AC Scenario 4 / design.md AIR-024
SYSTEM_PROMPT_TOKEN_BUDGET: int = 2_000
DISCHARGE_SUMMARY_TOKEN_BUDGET: int = 4_000
CONVERSATION_HISTORY_TOKEN_BUDGET: int = 2_000
TOTAL_CONTEXT_TOKEN_BUDGET: int = (
    SYSTEM_PROMPT_TOKEN_BUDGET
    + DISCHARGE_SUMMARY_TOKEN_BUDGET
    + CONVERSATION_HISTORY_TOKEN_BUDGET
)  # = 8_000

# Maximum number of messages retained in the deque before token-based pruning
MAX_HISTORY_MESSAGES: int = 10


class ConversationHistory(BaseModel):
    """In-memory representation of the conversation history for one session.

    FIFO pruning (US-043 AC Scenario 4):
        When the total token count of all messages exceeds
        CONVERSATION_HISTORY_TOKEN_BUDGET (2 K), the oldest messages are
        dropped from the deque until the budget is respected.
        The system prompt and discharge context are NEVER pruned.

    Serialisation:
        The `messages` deque is serialised to a JSON list before writing to
        Redis and deserialised back to a deque on read.
    """

    messages: list[ConversationMessage] = Field(default_factory=list)
    session_id: str
    encounter_id: str


# ---------------------------------------------------------------------------
# Audit event schema — no PHI, no message content
# ---------------------------------------------------------------------------

class ChatAuditEvent(BaseModel):
    """Structured audit record written to the HIPAA audit log.

    Only non-PHI metadata is included per US-043 Technical Notes:
        - encounter_id (UUID — not a name or MRN)
        - session_id (client-generated UUID)
        - message_timestamp (UTC datetime)
        - generation_type (LLM | FALLBACK)
    """

    encounter_id: str
    session_id: str
    message_timestamp: datetime
    generation_type: GenerationType
```

---

## Validation Checklist

```bash
# Syntax check
python -c "
import ast, pathlib
src = pathlib.Path('backend/app/agents/patient_comm/chatbot/schemas.py').read_text()
ast.parse(src)
print('schemas.py — syntax OK')
"

# Import check (requires pydantic ≥ 2.0 in the active environment)
python -c "
from backend.app.agents.patient_comm.chatbot.schemas import (
    ChatRequest, ChatResponse, ConversationMessage,
    ConversationHistory, ChatAuditEvent, GenerationType,
    TOTAL_CONTEXT_TOKEN_BUDGET,
)
assert TOTAL_CONTEXT_TOKEN_BUDGET == 8_000
print('All schemas importable — TOTAL_CONTEXT_TOKEN_BUDGET == 8000 ✓')
"

# UUID validation rejects non-UUID strings
python -c "
from pydantic import ValidationError
from backend.app.agents.patient_comm.chatbot.schemas import ChatRequest
try:
    ChatRequest(message='hi', encounter_id='not-a-uuid', session_id='also-not-uuid')
    raise AssertionError('Should have raised ValidationError')
except ValidationError as e:
    print('UUID validation enforcement ✓')
"
```

---

## Definition of Done

- [ ] `backend/app/agents/patient_comm/chatbot/schemas.py` created with all five schemas
- [ ] `TOTAL_CONTEXT_TOKEN_BUDGET == 8_000` asserted in validation script
- [ ] UUID field validators reject non-UUID strings (injection prevention)
- [ ] `ConversationMessage.content` excluded from all logging (security note present in docstring)
- [ ] `ChatAuditEvent` contains no PHI fields (no `message`, no patient name/MRN)
- [ ] Syntax check passes without errors
