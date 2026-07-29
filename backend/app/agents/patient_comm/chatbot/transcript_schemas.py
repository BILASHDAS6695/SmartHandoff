"""Pydantic schemas for chatbot transcript API (US-046).

Consumed by:
    - TASK-002: TranscriptPersistenceService (TranscriptMessageCreate — internal only)
    - TASK-003: GET /api/v1/encounters/{id}/chat-transcript endpoint
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.chatbot_transcript import MessageRole


class TranscriptMessageCreate(BaseModel):
    """Internal schema used by TranscriptPersistenceService — not exposed over API.

    Passed from the persistence service to the ORM layer; plaintext message
    is encrypted transparently by EncryptedString TypeDecorator at bind time.
    """

    encounter_id: uuid.UUID
    message: str
    role: MessageRole
    timestamp: datetime
    urgency_flag: bool = False
    escalated: bool = False


class TranscriptMessageRead(BaseModel):
    """Outbound: single decrypted transcript message returned by GET endpoint.

    EncryptedString TypeDecorator decrypts `message` transparently on SELECT.
    """

    id: uuid.UUID
    encounter_id: uuid.UUID
    message: str
    role: MessageRole
    timestamp: datetime
    urgency_flag: bool
    escalated: bool

    model_config = {"from_attributes": True}


class TranscriptPageResponse(BaseModel):
    """Paginated transcript response (US-046 AC Scenario 4).

    Default page size: 50 messages (most recent first from DB, returned in
    ascending timestamp order for chronological viewing).
    `next_cursor` is None when no older messages remain.
    """

    messages: list[TranscriptMessageRead]
    next_cursor: Optional[str] = None  # Opaque base64url-encoded timestamp cursor
    total_in_page: int
