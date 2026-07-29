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

from backend.app.db.base import Base  # shared declarative base


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
