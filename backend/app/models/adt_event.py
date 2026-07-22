"""AdtEvent ORM model — records each HL7 ADT message received by the HL7 Listener.

DR-022: `source_message_id` (MSH-10 field) carries a unique constraint to
prevent duplicate event processing on MLLP retransmissions.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class AdtEvent(Base, TimestampMixin):
    """HL7 ADT event record.

    One row per received HL7 message. Idempotency enforced by the unique
    constraint on `source_message_id` (MSH-10). Duplicate messages are
    ACK'd by the HL7 Listener and silently discarded (AIR-001, DR-022).
    """

    __tablename__ = "adt_event"

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

    # HL7 MSH-10 message control ID — unique per EHR message (DR-022)
    source_message_id: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
        unique=True,
        comment="HL7 MSH-10 message control ID; unique constraint prevents duplicate processing",
    )

    # HL7 event type (e.g., "A01", "A02", "A03", "A13")
    event_type: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        comment="HL7 ADT event type from MSH-9.2 (e.g., A01=Admit, A03=Discharge)",
    )

    event_timestamp: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        comment="Message timestamp from HL7 MSH-7",
    )

    sending_facility: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="HL7 MSH-4 sending facility identifier",
    )

    raw_message_path: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment="Cloud Storage path to archived raw HL7 message (AIR-003)",
    )

    processing_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="received",
        comment="One of: received, processing, processed, failed",
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="adt_events",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_adt_event_source_message_id", "source_message_id", unique=True),
        sa.Index("ix_adt_event_encounter_id", "encounter_id"),
        sa.Index("ix_adt_event_type_timestamp", "event_type", "event_timestamp"),
    )
