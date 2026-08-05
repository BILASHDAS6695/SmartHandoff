"""Encounter ORM model — the central clinical workflow entity.

DR-023: Encounter status transitions are enforced by the state machine
event listener in app/models/encounter_statemachine.py (TASK-006).
DR-005: Soft deletes via SoftDeleteMixin.
US-019: Patient identity resolution status tracking.
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
from app.models.patient import PatientResolutionStatus

if TYPE_CHECKING:
    from app.models.adt_event import AdtEvent
    from app.models.agent_task import AgentTask
    from app.models.appointment import Appointment
    from app.models.bed import Bed
    from app.models.document import Document
    from app.models.medication import Medication
    from app.models.patient import Patient


class EncounterStatus(str, enum.Enum):
    """Valid encounter lifecycle states (DR-023).

    Allowed transitions:
        REGISTERED    → ADMITTED         (A01: initial admission)
        PRE_ADMISSION → ADMITTED         (A01 re-admit after A11 cancel)
        ADMITTED      → TRANSFERRED      (A02: transfer)
        ADMITTED      → DISCHARGED       (A03: discharge)
        ADMITTED      → PRE_ADMISSION    (A11: cancel admit)      ← US-015
        TRANSFERRED   → DISCHARGED       (A03: discharge)
        TRANSFERRED   → ADMITTED         (A12: cancel transfer)   ← US-015
        DISCHARGED    → ADMITTED         (A13: cancel discharge)  ← US-015

    All other transitions are rejected with EncounterStateTransitionError (TASK-006).
    """

    REGISTERED    = "REGISTERED"
    PRE_ADMISSION = "PRE_ADMISSION"   # US-015: target of A11 cancel-admit
    ADMITTED      = "ADMITTED"
    TRANSFERRED   = "TRANSFERRED"
    DISCHARGED    = "DISCHARGED"


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

    # US-019: Patient identity resolution status tracking
    patient_resolution_status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default=PatientResolutionStatus.RESOLVED.value,
        index=True,  # Index for query performance
        comment="Status of patient identity resolution: RESOLVED, AMBIGUOUS, or UNRESOLVED (US-019)",
    )

    # Admission details
    # TEMPORARILY REMOVED - Missing in current DB schema (will be added in migration)
    # admit_date and discharge_date removed to prevent INSERT errors

    # Clinical context  
    # TEMPORARILY REMOVED - Missing in current DB schema (will be added in migration)
    # admitting_diagnosis, attending_physician_id removed to prevent INSERT errors

    unit: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="Current unit assignment; updated on transfer",
    )

    # US-015: records the unit before the last A02 transfer — enables A12 cancel-transfer revert
    # TEMPORARILY REMOVED - Missing in current DB schema (will be added in migration)
    # previous_unit removed to prevent INSERT errors

    # Risk stratification (Follow-up Care Agent, FR-052)
    risk_tier: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default=RiskTier.UNKNOWN.value,
        comment="Readmission risk tier: HIGH / MEDIUM / LOW / UNKNOWN",
    )
    # TEMPORARILY REMOVED - Missing in current DB schema (will be added in migration)
    # risk_score removed to prevent INSERT errors

    # US-036: ML-predicted discharge time (TR-007 ML Inference Service)
    # TEMPORARILY REMOVED - Missing in current DB schema (will be added in migration)
    # predicted_discharge_time, discharge_prediction_confidence, 
    # discharge_prediction_interval_hours removed to prevent INSERT errors

    # US-038: ED boarding alert tracking
    # TEMPORARILY REMOVED - Missing in current DB schema (will be added in migration)
    # boarding_alert_sent_at, boarding_alert_resolved_at removed to prevent INSERT errors

    # External identifiers
    # TEMPORARILY REMOVED - Missing in current DB schema (will be added in migration)
    # visit_number removed to prevent INSERT errors

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
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="encounter",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        # DR-004: Composite indexes for dashboard query performance
        # ix_encounter_patient_admit removed - admit_date will be added via Alembic migration
        # sa.Index("ix_encounter_patient_admit", "patient_id", "admit_date"),
        sa.Index("ix_encounter_unit_status", "unit", "status"),
        sa.Index("ix_encounter_risk_tier_status", "risk_tier", "status"),
        # Note: ix_encounter_deleted_at is already created by SoftDeleteMixin (index=True)
    )

    def transition_to(self, target: EncounterStatus) -> None:
        """Attempt a status transition, validated by the ORM state machine.

        For A13 (DISCHARGED → ADMITTED), the caller must set the session flag
        ``session.info["allow_a13_cancel_discharge"] = str(encounter.id)``
        before calling this method.

        Args:
            target: The new desired status.

        Raises:
            EncounterStateTransitionError: If the transition is not permitted.
        """
        self.status = target.value  # triggers ORM event listener in encounter_statemachine.py

    def __repr__(self) -> str:
        return (
            f"<Encounter id={self.id} "
            f"status={self.status} "
            f"risk={self.risk_tier}>"
        )
