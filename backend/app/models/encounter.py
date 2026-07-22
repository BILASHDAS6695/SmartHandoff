"""Encounter ORM model — the central clinical workflow entity.

DR-023: Encounter status transitions are enforced by the state machine
event listener in app/models/encounter_statemachine.py (TASK-006).
DR-005: Soft deletes via SoftDeleteMixin.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.adt_event import AdtEvent
    from app.models.agent_task import AgentTask
    from app.models.bed import Bed
    from app.models.document import Document
    from app.models.medication import Medication
    from app.models.patient import Patient


class EncounterStatus(str, enum.Enum):
    """Valid encounter lifecycle states (DR-023).

    Allowed transitions:
        REGISTERED  → ADMITTED
        ADMITTED    → TRANSFERRED
        ADMITTED    → DISCHARGED
        TRANSFERRED → DISCHARGED
        DISCHARGED  → ADMITTED  (only on A13 cancel-discharge event)

    All other transitions are rejected with EncounterStateTransitionError (TASK-006).
    """

    REGISTERED = "REGISTERED"
    ADMITTED = "ADMITTED"
    TRANSFERRED = "TRANSFERRED"
    DISCHARGED = "DISCHARGED"


class RiskTier(str, enum.Enum):
    """Readmission risk tier assigned by Follow-up Care Agent (FR-052)."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Encounter(Base, TimestampMixin, SoftDeleteMixin):
    """Hospital encounter (admission episode).

    An encounter is created on every A01 (Admit) ADT event and updated
    on A02 (Transfer), A03 (Discharge), and A13 (Cancel Discharge) events.

    The `status` field is guarded by the state machine event listener (TASK-006).
    """

    __tablename__ = "encounter"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # FK to patient — many encounters per patient
    patient_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("patient.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Encounter lifecycle state (DR-023)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=EncounterStatus.REGISTERED.value,
        comment="Encounter status; transitions enforced by state machine event listener",
    )

    # Admission details
    admit_date: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    discharge_date: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    # Clinical context
    admitting_diagnosis: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment="Primary admitting diagnosis (from ADT PV2.3 segment)",
    )
    attending_physician_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="Current unit assignment; updated on transfer",
    )

    # Risk stratification (Follow-up Care Agent, FR-052)
    risk_tier: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default=RiskTier.UNKNOWN.value,
        comment="Readmission risk tier: HIGH / MEDIUM / LOW / UNKNOWN",
    )
    risk_score: Mapped[float | None] = mapped_column(
        sa.Float,
        nullable=True,
        comment="Predicted readmission probability (0.0–1.0) from ML model",
    )

    # External identifiers
    visit_number: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="EHR visit/account number from ADT PV1.19",
    )

    # Relationships
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="encounters",
        lazy="select",
    )
    adt_events: Mapped[list["AdtEvent"]] = relationship(
        "AdtEvent",
        back_populates="encounter",
        lazy="select",
    )
    agent_tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask",
        back_populates="encounter",
        lazy="select",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="encounter",
        lazy="select",
    )
    medications: Mapped[list["Medication"]] = relationship(
        "Medication",
        back_populates="encounter",
        lazy="select",
    )

    __table_args__ = (
        # DR-004: Composite indexes for dashboard query performance
        sa.Index("ix_encounter_patient_admit", "patient_id", "admit_date"),
        sa.Index("ix_encounter_unit_status", "unit", "status"),
        sa.Index("ix_encounter_risk_tier_status", "risk_tier", "status"),
        sa.Index("ix_encounter_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Encounter id={self.id} "
            f"status={self.status} "
            f"risk={self.risk_tier}>"
        )
