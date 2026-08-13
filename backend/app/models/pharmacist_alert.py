"""SQLAlchemy model for pharmacist drug-interaction alerts.

Design refs:
    US-031 AC Scenario 1 — severity, drug_pair, interaction_description, source
    US-031 AC Scenario 4 — interaction_check_status persisted on reconciliation
    US-032 AC Scenario 1 — HIGH_RISK_DRUG_CLASS alert fields (drug_class, drug_name)
    US-032 AC Scenario 2 — Resolution workflow fields (status, resolution_type, etc.)
    US-032 AC Scenario 3 — SLA monitoring (sla_breached)
    ADR-007              — PHI fields encrypted at ORM layer (drug names are not PHI)
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PharmacistAlert(Base):
    """Represents a pharmacist-facing drug interaction alert.

    Attributes:
        id: UUID primary key.
        encounter_id: FK to the encounter that triggered the alert.
        alert_type: Always ``PHARMACIST_ALERT``.
        severity: ``HIGH``, ``MEDIUM``, or ``LOW``.
        drug_pair: JSON array of two drug names, e.g. ``["Warfarin","Aspirin"]``.
        interaction_description: Free-text description from RxNav or OpenFDA.
        source: ``RXNAV``, ``OPENFDA``, or ``SYSTEM`` (degradation alert).
        interaction_check_status: ``COMPLETE`` or ``INCOMPLETE``.
        metadata_: Additional source-specific metadata dict.
        created_at: UTC timestamp of alert creation.
    """

    __tablename__ = "pharmacist_alerts"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    encounter_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_type: Mapped[str] = mapped_column(
        Enum(
            "PHARMACIST_ALERT",
            "HIGH_RISK_DRUG_CLASS",
            name="alert_type_enum",
        ),
        nullable=False,
        default="PHARMACIST_ALERT",
    )
    severity: Mapped[str] = mapped_column(
        Enum("HIGH", "MEDIUM", "LOW", name="alert_severity_enum"),
        nullable=False,
    )
    drug_pair: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    interaction_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="RXNAV")
    interaction_check_status: Mapped[str] = mapped_column(
        Enum("COMPLETE", "INCOMPLETE", name="check_status_enum"),
        nullable=False,
        default="COMPLETE",
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # HIGH_RISK_DRUG_CLASS alert fields (US-032 AC Scenario 1)
    drug_class: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="ISMP high-risk class: ANTICOAGULANT | INSULIN | OPIOID | CHEMOTHERAPY",
    )
    drug_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Single drug name triggering a HIGH_RISK_DRUG_CLASS alert",
    )

    # Resolution workflow fields (US-032 AC Scenario 2)
    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "RESOLVED", name="alert_status_enum"),
        nullable=False,
        default="ACTIVE",
        index=True,
    )
    resolution_type: Mapped[str | None] = mapped_column(
        Enum(
            "REVIEWED_ACCEPTABLE",
            "DOSE_ADJUSTED",
            "DRUG_CHANGED",
            "DISCONTINUED",
            name="alert_resolution_type_enum",
        ),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SLA monitoring (US-032 AC Scenario 3)
    sla_breached: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Set True by SLA monitor when alert exceeds 24h unresolved threshold",
    )
