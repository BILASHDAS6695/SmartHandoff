"""ChatbotTranscript ORM model — patient chatbot conversation messages.

DR-016: Encrypted and retained 7 years with encounter.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.encryption import EncryptedString
from app.db.mixins import TimestampMixin


class ChatbotTranscript(Base, TimestampMixin):
    """Single message in a patient–chatbot conversation.

    `message_content` is encrypted at rest (DR-016, US-007).
    Urgency detection flag set by the Patient Communication Agent (FR-063).
    """

    __tablename__ = "chatbot_transcript"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Message direction
    role: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        comment="One of: patient, assistant — identifies message sender",
    )

    # PHI-containing content encrypted via US-007 (DR-016)
    message_content: Mapped[str] = mapped_column(
        EncryptedString,
        nullable=False,
        comment="Encrypted chatbot message body (DR-016)",
    )

    is_urgent: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        comment="Set True by Patient Communication Agent on urgency detection (FR-063)",
    )

    escalated_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when urgency escalation was sent to care team",
    )

    __table_args__ = (
        sa.Index("ix_chatbot_encounter_id", "encounter_id"),
        sa.Index("ix_chatbot_urgent", "encounter_id", "is_urgent"),
    )
