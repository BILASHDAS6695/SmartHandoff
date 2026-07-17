---
id: TASK-001
title: "ORM Model, Pydantic Schemas & Alembic Migration — ChatbotEscalation"
user_story: US-045
epic: EP-008
sprint: 2
layer: Backend / Data
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-043, US-044]
---

# TASK-001: ORM Model, Pydantic Schemas & Alembic Migration — ChatbotEscalation

> **Story:** US-045 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-045 requires a `ChatbotEscalation` table to record every care team escalation triggered by urgency detection (US-044). This task creates the SQLAlchemy ORM model, all Pydantic schemas consumed by subsequent tasks, and the Alembic migration that provisions the table in Cloud SQL.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `ChatbotEscalation` | SQLAlchemy ORM model | Persists escalation events: who was notified, when, and when acknowledged |
| `EscalationCreate` | Pydantic schema — inbound | Payload for `POST /api/v1/chat/escalate` |
| `EscalationRead` | Pydantic schema — outbound | Response returned by GET and as confirmation on POST |
| `EscalationAcknowledge` | Pydantic schema — inbound | Payload for `PATCH /api/v1/chat/escalation/{id}/acknowledge` |
| `EscalationAlertPayload` | Pydantic schema — Pub/Sub | Payload published to `notification-requests` topic |
| `EscalationConfirmedMessage` | Pydantic schema — chat push | `{type: ESCALATION_CONFIRMED}` pushed to patient chat UI via SignalR |
| Alembic migration | `versions/xxxx_add_chatbot_escalation.py` | Creates `chatbot_escalation` table in Cloud SQL PostgreSQL |

**ORM model columns (US-045 DoD):**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | Auto-generated `uuid4` |
| `encounter_id` | UUID FK → `encounter.id` | Links escalation to the patient encounter |
| `transcript_message_id` | UUID FK → `chat_transcript.id` | The urgency message that triggered escalation |
| `notified_user_id` | UUID FK → `app_user.id` | On-call nurse resolved at publish time |
| `notified_at` | DateTime UTC | Timestamp of Pub/Sub publish (not nurse receipt) |
| `acknowledged_at` | DateTime UTC, nullable | Set by PATCH /acknowledge; null means unacknowledged |
| `channel` | VARCHAR(20) | `SMS` or `IN_APP` — notification channel used |
| `urgency_message` | TEXT | Verbatim patient urgency message (minimum PHI: no name, DOB, MRN stored here) |
| `created_at` | DateTime UTC | Row insert time |

**Design references:**
- design.md §3.1 — Patient Communication Agent: chatbot, urgency detection, escalation routing
- design.md §6.1 DR-002 — PHI field-level encryption; `urgency_message` assessed as minimum-PHI (no direct identifier — not encrypted)
- design.md §6.1 DR-005 — soft-delete pattern: `deleted_at` column on patient/encounter records (not applied to `chatbot_escalation` — escalation records are audit data, never deleted)
- design.md §6.1 DR-003 — `chatbot_escalation` is append-only audit data; no UPDATE after creation except `acknowledged_at` via dedicated endpoint
- design.md §7.5 AIR-040 — Notification Service reads `notification-requests` Pub/Sub topic; `EscalationAlertPayload` must match the `channel` field expected by the Notification Service
- US-045 AC Scenario 3 — GET response must include `transcript_message_id`, `urgency_message`, `notified_user_id`, `acknowledged_at`, `acknowledgement_time_minutes`
- US-045 Technical Notes — `{type: ESCALATION_CONFIRMED}` chat message pushed immediately; `notified_user_id` resolved from `app_user` table

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `EscalationConfirmedMessage` schema defines the `ESCALATION_CONFIRMED` chat push payload |
| Scenario 2 | `acknowledged_at` column on `ChatbotEscalation` enables acknowledgement time calculation |
| Scenario 3 | `EscalationRead` schema exposes all required fields including `acknowledgement_time_minutes` |
| Scenario 4 | `encounter_id` FK on `ChatbotEscalation` enables JWT-scoped patient filtering in TASK-004 |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/patient_comm/escalation
touch backend/app/agents/patient_comm/escalation/__init__.py
touch backend/app/agents/patient_comm/escalation/models.py
touch backend/app/agents/patient_comm/escalation/schemas.py
```

### 2. Implement `backend/app/agents/patient_comm/escalation/schemas.py`

```python
"""Pydantic schemas for the Care Team Escalation feature (US-045).

All schemas are consumed by:
    - task_002: POST /api/v1/chat/escalate FastAPI endpoint
    - task_003: PATCH /api/v1/chat/escalation/{id}/acknowledge endpoint
    - task_004: GET /api/v1/chat/escalations endpoint
    - task_002: EscalationAlertPayload published to Pub/Sub notification-requests topic

Design refs:
    US-045 AC Scenarios 1–4
    design.md §7.5 AIR-040 — notification-requests Pub/Sub topic payload format
    design.md §8.2 — patient JWT encounter scope
    US-045 Technical Notes — ESCALATION_CONFIRMED message type for SignalR push
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class NotificationChannel(str, Enum):
    """Notification channel used to alert the on-call nurse.

    Matches the `channel` field expected by the Notification Service
    (design.md §7.5 AIR-040).
    """

    SMS = "SMS"
    IN_APP = "IN_APP"


class EscalationMessageType(str, Enum):
    """Chat UI push message type for escalation confirmation.

    US-045 Technical Notes: pushed as a special message type, not a
    regular chatbot response, so the Angular client renders a distinct
    confirmation card rather than a chat bubble.
    """

    ESCALATION_CONFIRMED = "ESCALATION_CONFIRMED"


# ---------------------------------------------------------------------------
# Inbound schemas
# ---------------------------------------------------------------------------

class EscalationCreate(BaseModel):
    """Payload accepted by POST /api/v1/chat/escalate.

    Security note (US-045 AC Scenario 4):
        The API layer verifies that `encounter_id` matches the patient JWT
        `encounter_id` claim before any DB write or Pub/Sub publish.
        Mismatch MUST return HTTP 403.

    PHI note (design.md §6.1 DR-002 / AIR-021):
        `urgency_message` contains the verbatim patient message that triggered
        urgency detection. It does not contain direct identifiers (name, DOB,
        MRN) — it is the patient's own words. It is NOT encrypted at field
        level but MUST NOT appear in Cloud Logging output.
    """

    encounter_id: Annotated[
        str,
        Field(description="UUID of the patient encounter — must match JWT claim"),
    ]
    transcript_message_id: Annotated[
        str,
        Field(description="UUID of the chat_transcript row that triggered urgency detection"),
    ]
    urgency_message: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description="Verbatim patient urgency message — minimum PHI, no direct identifiers",
        ),
    ]
    channel: NotificationChannel = Field(
        default=NotificationChannel.SMS,
        description="Notification channel for on-call nurse alert",
    )

    @field_validator("encounter_id", "transcript_message_id")
    @classmethod
    def validate_uuid(cls, value: str, info) -> str:
        """Reject non-UUID values to prevent Redis/DB key injection attacks."""
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError(f"{info.field_name} must be a valid UUID v4") from exc
        return value


class EscalationAcknowledge(BaseModel):
    """Payload accepted by PATCH /api/v1/chat/escalation/{id}/acknowledge.

    Staff-only: nurse, physician, or admin role required.
    The `acknowledged_at` timestamp is set server-side (UTC); this schema
    exists as a request body placeholder for future extension (e.g., notes).
    """

    pass  # Body intentionally empty — acknowledgement is idempotent by timestamp


# ---------------------------------------------------------------------------
# Outbound schemas
# ---------------------------------------------------------------------------

class EscalationRead(BaseModel):
    """Escalation record returned by GET /api/v1/chat/escalations.

    US-045 AC Scenario 3 requires all these fields in the response.
    `acknowledgement_time_minutes` is a computed property — null if unacknowledged.
    """

    model_config = {"from_attributes": True}

    id: str
    encounter_id: str
    transcript_message_id: str
    notified_user_id: str
    notified_at: datetime
    acknowledged_at: datetime | None
    channel: NotificationChannel
    urgency_message: str
    created_at: datetime

    @computed_field
    @property
    def acknowledgement_time_minutes(self) -> float | None:
        """Minutes between notified_at and acknowledged_at.

        Used by US-045 DoD: if >2 minutes, the encounter is flagged for
        response time review (logged as a Cloud Monitoring metric in TASK-003).
        Returns None if not yet acknowledged.
        """
        if self.acknowledged_at is None:
            return None
        delta = self.acknowledged_at - self.notified_at
        return round(delta.total_seconds() / 60, 2)


# ---------------------------------------------------------------------------
# Pub/Sub payload schema
# ---------------------------------------------------------------------------

class EscalationAlertPayload(BaseModel):
    """Payload published to the 'notification-requests' Pub/Sub topic.

    Consumed by the Notification Service (design.md §7.5 AIR-040) to
    dispatch an SMS or in-app alert to the on-call nurse.

    PHI minimisation (design.md AIR-021):
        Only `patient_first_name` included — no surname, DOB, MRN, or
        full discharge details. The urgency summary is the patient's own
        words, truncated to 200 characters to minimise PHI exposure in
        the notification channel.
    """

    escalation_id: str = Field(description="UUID of the ChatbotEscalation row")
    encounter_id: str
    notified_user_id: str = Field(description="app_user.id of on-call nurse")
    patient_first_name: str = Field(description="Patient first name only — minimum PHI")
    urgency_message_summary: Annotated[
        str,
        Field(
            max_length=200,
            description="Truncated urgency message for the notification body",
        ),
    ]
    channel: NotificationChannel
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of Pub/Sub publish",
    )

    @model_validator(mode="before")
    @classmethod
    def truncate_urgency_summary(cls, values: dict) -> dict:
        """Enforce 200-char max on urgency_message_summary before validation."""
        if "urgency_message_summary" in values:
            values["urgency_message_summary"] = values["urgency_message_summary"][:200]
        return values


# ---------------------------------------------------------------------------
# SignalR chat push schema
# ---------------------------------------------------------------------------

class EscalationConfirmedMessage(BaseModel):
    """Pushed to the patient's chat UI immediately after escalation is created.

    US-045 Technical Notes:
        - Type is ESCALATION_CONFIRMED — not a regular chatbot reply
        - Angular client renders a distinct confirmation card
        - Displayed immediately after urgency detection, NOT after nurse
          acknowledgement (AC Scenario 1 confirmation text is shown here)
        - Fire-and-forget: chat response is NOT blocked on Pub/Sub delivery

    SignalR group: 'encounter-{encounter_id}' (design.md §3.3 SignalR hub)
    """

    type: EscalationMessageType = EscalationMessageType.ESCALATION_CONFIRMED
    encounter_id: str
    message: str = Field(
        default=(
            "Your care team has been notified and will contact you within 2 minutes. "
            "If this is life-threatening, call 911 immediately."
        ),
        description="Confirmation message shown in the patient's chat UI (AC Scenario 1)",
    )
    escalation_id: str = Field(description="UUID of the ChatbotEscalation row")
```

### 3. Implement `backend/app/agents/patient_comm/escalation/models.py`

```python
"""SQLAlchemy ORM model for the ChatbotEscalation table (US-045).

Table: chatbot_escalation

Audit semantics (design.md §6.1 DR-003):
    This table is effectively append-only: rows are inserted on POST /escalate
    and the `acknowledged_at` column is updated once on PATCH /acknowledge.
    No other UPDATE or DELETE operations are permitted on this table.

PHI handling (design.md §6.1 DR-002):
    `urgency_message` stores the patient's verbatim message. It does not
    contain direct identifiers (name, DOB, MRN) and is NOT encrypted at
    field level. However, it MUST NOT appear in Cloud Logging output.

Design refs:
    US-045 DoD — all required columns defined here
    design.md §6.1 DR-004 — composite index on (encounter_id, notified_at DESC)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base_class import Base  # shared declarative base


class ChatbotEscalation(Base):
    """Persists care team escalation events triggered by urgency detection.

    One row per escalation. The `acknowledged_at` column remains NULL until
    a staff member calls PATCH /api/v1/chat/escalation/{id}/acknowledge.

    US-045 DoD columns:
        encounter_id, transcript_message_id, notified_user_id,
        notified_at, acknowledged_at, channel
    """

    __tablename__ = "chatbot_escalation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Primary key — auto-generated UUID v4",
    )
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="FK to encounter — used for patient-scoped GET queries",
    )
    transcript_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("chat_transcript.id", ondelete="RESTRICT"),
        nullable=False,
        doc="FK to the chat_transcript row that triggered urgency detection",
    )
    notified_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
        nullable=False,
        doc="FK to app_user — the on-call nurse who received the alert",
    )
    notified_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        doc="UTC timestamp when Pub/Sub escalation alert was published",
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
        doc="UTC timestamp when on-call nurse acknowledged the alert; NULL = unacknowledged",
    )
    channel: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        doc="Notification channel used: SMS or IN_APP",
    )
    urgency_message: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        doc="Verbatim patient urgency message — minimum PHI; MUST NOT appear in logs",
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=sa.text("NOW()"),
        doc="Row insert timestamp",
    )

    # Composite index for patient-scoped queries sorted by recency (TASK-004)
    __table_args__ = (
        sa.Index(
            "ix_chatbot_escalation_encounter_notified",
            "encounter_id",
            "notified_at",
            postgresql_using="btree",
        ),
    )
```

### 4. Generate Alembic migration

```bash
# Run from the backend service root (where alembic.ini lives)
cd backend
alembic revision --autogenerate \
  -m "add_chatbot_escalation_table_us045"
```

Review the generated file in `alembic/versions/` and confirm:
- `chatbot_escalation` table is created with all columns
- FKs to `encounter`, `chat_transcript`, `app_user` are present
- Index `ix_chatbot_escalation_encounter_notified` is created
- `op.drop_table("chatbot_escalation")` in `downgrade()` is present

### 5. Apply migration to dev database

```bash
alembic upgrade head
```

Verify with:
```bash
psql $DATABASE_URL -c "\d chatbot_escalation"
```

---

## Validation Checklist

- [ ] `python -m py_compile backend/app/agents/patient_comm/escalation/schemas.py` — zero errors
- [ ] `python -m py_compile backend/app/agents/patient_comm/escalation/models.py` — zero errors
- [ ] `alembic upgrade head` completes without error on dev DB
- [ ] `\d chatbot_escalation` shows all 9 columns + composite index
- [ ] `alembic downgrade -1` then `alembic upgrade head` round-trips cleanly
- [ ] `EscalationRead.acknowledgement_time_minutes` returns `None` for unacknowledged rows
- [ ] `EscalationRead.acknowledgement_time_minutes` returns correct float for acknowledged rows
- [ ] `EscalationCreate.validate_uuid` raises `ValidationError` for non-UUID `encounter_id`
- [ ] `EscalationAlertPayload.urgency_message_summary` is truncated to 200 chars
- [ ] `EscalationConfirmedMessage.message` contains "2 minutes" and "911" (AC Scenario 1 text)

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-043 TASK-001 | Story | `chat_transcript` table must exist as FK target |
| `backend/app/db/base_class.py` | Module | Shared `Base` declarative class |
| Alembic configured | Infra | Migration runner must be set up |
