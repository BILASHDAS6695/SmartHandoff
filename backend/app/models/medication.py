"""Medication ORM model — patient medication list per encounter.

Used by the Medication Reconciliation Agent (FR-030–FR-035).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class Medication(Base, TimestampMixin):
    """A medication record associated with a patient encounter.

    Populated by the Medication Reconciliation Agent from FHIR
    MedicationRequest resources. Interaction severity set by RxNav API (AIR-050).
    """

    __tablename__ = "medication"

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

    drug_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    rxcui: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        comment="RxNorm Concept Unique Identifier for drug interaction lookups (AIR-050)",
    )
    dose: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    frequency: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    source: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="admission",
        comment="One of: admission, discharge, home — reconciliation list source",
    )

    interaction_severity: Mapped[str | None] = mapped_column(
        sa.String(16),
        nullable=True,
        comment="One of: HIGH, MEDIUM, LOW — from RxNav interaction check (AIR-051)",
    )

    reconciliation_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pending",
        comment="One of: pending, reconciled, flagged, incomplete",
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="medications",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_medication_encounter_id", "encounter_id"),
        sa.Index("ix_medication_rxcui", "rxcui"),
        sa.Index("ix_medication_severity", "interaction_severity"),
    )
