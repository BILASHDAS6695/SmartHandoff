"""ChatbotTranscript ORM model — patient chatbot conversation messages (US-046).

DR-016: Encrypted and retained 7 years with encounter.
US-046: Each patient message and assistant reply persisted with urgency flags and escalation status.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.encryption import EncryptedString
from app.db.mixins import TimestampMixin


class MessageRole(str, enum.Enum):
    """Message direction in chatbot transcript."""

    PATIENT = "PATIENT"
    ASSISTANT = "ASSISTANT"


class ChatbotTranscript(TimestampMixin, Base):
    """Single message in a patient–chatbot conversation.

    SECURITY (US-046, DR-016):
        The `message` column stores AES-256-GCM ciphertext via EncryptedString
        (US-007 TypeDecorator). The raw database value is NEVER the patient's
        plaintext message.

    IMMUTABILITY (US-046, DR-003):
        RLS policy enforces app_write cannot UPDATE or DELETE rows.
        Only INSERT is permitted — audit-log immutability pattern from US-008.

    URGENCY & ESCALATION (US-046, US-044, US-045):
        urgency_flag: Set by UrgencyDetector when patient message signals urgency
        escalated: Set when escalation alert was published to Pub/Sub
    """

    __tablename__ = "chatbot_transcript"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    message: Mapped[str] = mapped_column(
        EncryptedString,
        nullable=False,
        comment="Encrypted chatbot message body (AES-256-GCM, DR-016, US-046)",
    )

    role: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
        comment="PATIENT or ASSISTANT — discriminates message origin",
    )

    timestamp: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        comment="UTC message timestamp; used for chronological ordering and pagination",
    )

    urgency_flag: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
        comment="True when UrgencyDetector flagged patient message as urgent (US-044)",
    )

    escalated: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
        comment="True when escalation alert was published to Pub/Sub (US-045)",
    )

    __table_args__ = (
        sa.Index(
            "ix_chatbot_transcript_encounter_timestamp",
            "encounter_id",
            "timestamp",
        ),
    )
