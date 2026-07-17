---
id: TASK-001
title: "ORM Model, Pydantic Schemas & Alembic Migration — ChatbotTranscript"
user_story: US-046
epic: EP-008
sprint: 2
layer: Backend / Data
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-007, US-008, US-043]
---

# TASK-001: ORM Model, Pydantic Schemas & Alembic Migration — ChatbotTranscript

> **Story:** US-046 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-046 requires a `chatbot_transcript` table to persist every chatbot message (patient + assistant) against the patient's encounter, with AES-256-GCM encryption on the `message` field and urgency flags preserved. This task creates the SQLAlchemy ORM model, all Pydantic schemas, the Alembic migration that provisions the table, and the RLS policy extension that enforces transcript immutability.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `ChatbotTranscript` | SQLAlchemy ORM model | Persists each chatbot message with encrypted content, role, urgency_flag, escalated |
| `MessageRole` | Python Enum | `PATIENT` or `ASSISTANT` — discriminates message origin |
| `TranscriptMessageCreate` | Pydantic schema — internal | Used by `TranscriptPersistenceService` (TASK-002); not exposed over API |
| `TranscriptMessageRead` | Pydantic schema — outbound | Decrypted message object returned by the GET transcript endpoint |
| `TranscriptPageResponse` | Pydantic schema — outbound | Paginated wrapper: `{ messages: list[TranscriptMessageRead], next_cursor: str \| None, total_in_page: int }` |
| Alembic migration | `versions/xxxx_add_chatbot_transcript.py` | Creates `chatbot_transcript` table; adds RLS immutability policy (US-008 pattern) |

**ORM model columns (US-046 DoD):**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | Auto-generated `uuid4` |
| `encounter_id` | UUID FK → `encounter.id` | Links transcript to the patient encounter; indexed |
| `message` | `EncryptedString` (AES-256-GCM) | Encrypted message content; raw DB value is ciphertext; reuses US-007 TypeDecorator |
| `role` | `VARCHAR(10)` (`MessageRole`) | `PATIENT` or `ASSISTANT` |
| `timestamp` | `TIMESTAMPTZ` | UTC message timestamp; set at insert time; used for chronological ordering |
| `urgency_flag` | `BOOLEAN` NOT NULL DEFAULT FALSE | True when urgency detection was triggered for this message (US-044) |
| `escalated` | `BOOLEAN` NOT NULL DEFAULT FALSE | True when a `chatbot_escalation` Pub/Sub record was published for this message (US-045) |
| `created_at` | `TIMESTAMPTZ` | Row insert time; set by `TimestampMixin` |

**Design references:**
- design.md §3.1 — Patient Communication Agent: chatbot, urgency detection, escalation routing
- design.md §6.1 DR-002 — PHI field-level encryption: `message` contains patient symptom disclosures → `EncryptedString` required
- design.md §6.1 DR-003 — `chatbot_transcript` is append-only clinical/audit data; no UPDATE or DELETE for application role
- US-007 — `EncryptedString` TypeDecorator at `backend/app/db/encryption.py`; reused without modification
- US-008 — RLS policy pattern: `CREATE POLICY ... AS RESTRICTIVE FOR ALL TO app_write USING (false)` blocks UPDATE/DELETE; separate `PERMISSIVE FOR INSERT` allows persistence writes
- US-046 AC Scenario 3 — direct SQL query must return ciphertext, not plaintext
- US-046 Technical Notes — pagination default 50 messages; no UPDATE or DELETE for application role

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `ChatbotTranscript` ORM model defines all required columns: `encounter_id`, `message`, `role`, `timestamp`, `urgency_flag`, `escalated` |
| Scenario 2 | `urgency_flag` and `escalated` boolean columns defined on ORM; set to correct values by TASK-002 persistence service |
| Scenario 3 | `message` column uses `EncryptedString` TypeDecorator → raw DB value is AES-256-GCM ciphertext |
| Scenario 4 | `TranscriptMessageRead` exposes decrypted `message` for API response; `TranscriptPageResponse` provides cursor-based pagination |

---

## Implementation Steps

### 1. Create module structure

```bash
touch backend/app/models/chatbot_transcript.py
touch backend/app/agents/patient_comm/chatbot/transcript_schemas.py
```

### 2. Implement `backend/app/models/chatbot_transcript.py`

```python
"""ORM model for chatbot transcript messages (US-046).

SECURITY:
    The `message` column stores AES-256-GCM ciphertext via EncryptedString
    (US-007 TypeDecorator). The raw database value is NEVER the patient's
    plaintext message.

IMMUTABILITY:
    The RLS policy in the Alembic migration enforces that the app_write role
    cannot UPDATE or DELETE rows. Only INSERT is permitted — mirrors the
    audit_log immutability pattern from US-008.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.encryption import EncryptedString
from app.db.mixins import TimestampMixin


class MessageRole(str, enum.Enum):
    PATIENT = "PATIENT"
    ASSISTANT = "ASSISTANT"


class ChatbotTranscript(TimestampMixin, Base):
    __tablename__ = "chatbot_transcript"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounter.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    urgency_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    escalated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        Index(
            "ix_chatbot_transcript_encounter_timestamp",
            "encounter_id",
            "timestamp",
        ),
    )
```

### 3. Implement `backend/app/agents/patient_comm/chatbot/transcript_schemas.py`

```python
"""Pydantic schemas for chatbot transcript API (US-046).

Consumed by:
    - task_002: TranscriptPersistenceService (TranscriptMessageCreate — internal only)
    - task_003: GET /api/v1/encounters/{id}/chat-transcript endpoint
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.chatbot_transcript import MessageRole


class TranscriptMessageCreate(BaseModel):
    """Internal schema used by TranscriptPersistenceService — not exposed over API."""
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
    """Paginated transcript response.

    Default page size: 50 messages (most recent first, returned in ascending order).
    `next_cursor` is None when no older messages remain.
    """
    messages: list[TranscriptMessageRead]
    next_cursor: Optional[str] = None   # Opaque base64url-encoded timestamp cursor
    total_in_page: int
```

### 4. Create Alembic migration `backend/alembic/versions/xxxx_add_chatbot_transcript.py`

```python
"""Add chatbot_transcript table with RLS immutability policy.

Revision ID: <generated by alembic>
Revises: <previous revision>
Create Date: 2026-07-17

Design refs:
    US-046: chatbot_transcript ORM, AES-256-GCM encrypted message, urgency/escalated flags
    US-008: RLS pattern — RESTRICTIVE USING (false) blocks UPDATE/DELETE for app_write;
            separate PERMISSIVE FOR INSERT WITH CHECK (true) allows persistence writes
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    op.create_table(
        "chatbot_transcript",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "encounter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encounter.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Text column — EncryptedString TypeDecorator stores AES-256-GCM ciphertext here
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "urgency_flag", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column(
            "escalated", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_chatbot_transcript_encounter_timestamp",
        "chatbot_transcript",
        ["encounter_id", "timestamp"],
    )

    # RLS — extend immutability pattern from US-008
    # app_write role must not UPDATE or DELETE clinical transcript rows
    op.execute("ALTER TABLE chatbot_transcript ENABLE ROW LEVEL SECURITY")

    # RESTRICTIVE policy — AND-combined with every row check → blocks all operations
    op.execute("""
        CREATE POLICY transcript_immutable
            ON chatbot_transcript
            AS RESTRICTIVE
            FOR ALL
            TO app_write
            USING (false)
    """)

    # PERMISSIVE INSERT — explicitly allows persistence service to write new rows
    op.execute("""
        CREATE POLICY transcript_insert_allowed
            ON chatbot_transcript
            AS PERMISSIVE
            FOR INSERT
            TO app_write
            WITH CHECK (true)
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS transcript_insert_allowed ON chatbot_transcript"
    )
    op.execute(
        "DROP POLICY IF EXISTS transcript_immutable ON chatbot_transcript"
    )
    op.drop_index(
        "ix_chatbot_transcript_encounter_timestamp", "chatbot_transcript"
    )
    op.drop_table("chatbot_transcript")
```

---

## Definition of Done Checklist

- [ ] `backend/app/models/chatbot_transcript.py` created with `ChatbotTranscript` ORM model and `MessageRole` enum
- [ ] `message` column uses `EncryptedString` TypeDecorator (not `String` or `Text` directly on the model)
- [ ] `urgency_flag` and `escalated` boolean columns with `server_default="false"`
- [ ] Composite index on `(encounter_id, timestamp)` defined in `__table_args__`
- [ ] `backend/app/agents/patient_comm/chatbot/transcript_schemas.py` created with `TranscriptMessageCreate`, `TranscriptMessageRead`, `TranscriptPageResponse`
- [ ] Alembic migration created; `alembic upgrade head` applies cleanly on dev Cloud SQL instance
- [ ] RLS `RESTRICTIVE` policy `transcript_immutable` blocks UPDATE/DELETE for `app_write`
- [ ] `PERMISSIVE` INSERT policy `transcript_insert_allowed` allows new row creation
- [ ] No existing test failures introduced
