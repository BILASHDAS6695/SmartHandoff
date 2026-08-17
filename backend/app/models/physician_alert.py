"""SQLAlchemy model for physician-facing clinical review alerts.

Design refs:
    US-030 extension — Physician medication review alert triggered by the
    Medication Reconciliation Agent so a physician can review, update, or
    add discharge medications for a specific encounter.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PhysicianAlert(Base):
    """Represents a physician-facing alert requiring clinical review/action.

    Attributes:
        id: UUID primary key.
        encounter_id: FK to the encounter that triggered the alert.
        patient_id: Optional FK to the patient for display/filtering.
        alert_type: Category of physician alert (e.g. MEDICATION_REVIEW).
        severity: HIGH, MEDIUM, or LOW.
        title: Short human-readable summary.
        message: Detailed instructions/context.
        status: ACTIVE or RESOLVED.
        resolution_type: How the alert was resolved (optional).
        resolution_note: Free-text note (optional).
        resolved_by_user_id: User that resolved the alert (optional).
        resolved_at: Resolution timestamp (optional).
        created_at: UTC timestamp of alert creation.
    """

    __tablename__ = "physician_alerts"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    encounter_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    alert_type: Mapped[str] = mapped_column(
        Enum("MEDICATION_REVIEW", name="physician_alert_type_enum"),
        nullable=False,
        default="MEDICATION_REVIEW",
    )
    severity: Mapped[str] = mapped_column(
        Enum("HIGH", "MEDIUM", "LOW", name="physician_alert_severity_enum"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "RESOLVED", name="physician_alert_status_enum"),
        nullable=False,
        default="ACTIVE",
    )
    resolution_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
