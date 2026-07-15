---
id: TASK-004
title: "Define ORM Model — `Encounter` with Status Enum and Patient Relationship"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002, TASK-003]
---

# TASK-004: Define ORM Model — `Encounter` with Status Enum and Patient Relationship

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

The `Encounter` model is the central clinical workflow entity in SmartHandoff. Every ADT event, agent task, AI-generated document, and bed assignment references an `Encounter`. Its `status` column drives the encounter state machine (DR-023), which is implemented in TASK-006.

This task establishes the `Encounter` model with:
1. The `EncounterStatus` enum controlling allowed status values
2. A FK relationship to `Patient` (many encounters per patient)
3. Risk tier column for the Follow-up Care Agent (FR-052)
4. `admit_date` and `discharge_date` for timeline queries
5. Composite indexes required by DR-004 for dashboard query performance
6. `SoftDeleteMixin` for DR-005 compliance

The state machine event listener (TASK-006) will attach to `Encounter.status` using SQLAlchemy's `@event.listens_for` — the model definition here is its prerequisite.

---

## Acceptance Criteria Addressed

| US-006 AC | Requirement |
|---|---|
| **Scenario 2** | State machine: `status` column transitions must be validated — the `EncounterStatus` enum and model structure enable TASK-006 to attach the validator |
| **Scenario 4** | Soft delete: `Encounter` inherits `SoftDeleteMixin`; `deleted_at` column present |
| **DoD** | ORM model defined for `encounter` table with correct column types, relationships, and constraints |

---

## Implementation Steps

### 1. Define `EncounterStatus` Enum in `backend/app/models/encounter.py`

The encounter state machine (DR-023) restricts status transitions. The enum must define all valid states:

```python
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
```

### 2. Define the `Encounter` Model Class

```python
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
```

### 3. Update `backend/app/models/__init__.py`

Add `Encounter` and the enums to the exports:

```python
from app.models.app_user import AppUser
from app.models.bed import Bed
from app.models.encounter import Encounter, EncounterStatus, RiskTier
from app.models.patient import Patient

__all__ = [
    "AppUser",
    "Bed",
    "Encounter",
    "EncounterStatus",
    "Patient",
    "RiskTier",
]
```

---

## Definition of Done

- [ ] `backend/app/models/encounter.py` defines `EncounterStatus` enum with four states: `REGISTERED`, `ADMITTED`, `TRANSFERRED`, `DISCHARGED`
- [ ] `Encounter` model includes `patient_id` FK to `patient.id` with `ondelete="RESTRICT"`
- [ ] `Encounter.status` column uses `String(32)` (not a DB-level enum type) to allow migration without DB enum management
- [ ] `Encounter` includes `risk_tier` (String, server_default `UNKNOWN`) and `risk_score` (Float, nullable)
- [ ] `Encounter` inherits both `TimestampMixin` and `SoftDeleteMixin`
- [ ] Three composite indexes defined per DR-004: `(patient_id, admit_date)`, `(unit, status)`, `(risk_tier, status)`
- [ ] All relationships declared with `lazy="select"` (explicit loading strategy)
- [ ] `backend/app/models/__init__.py` exports `Encounter`, `EncounterStatus`, `RiskTier`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-002 | Preceding task | `TimestampMixin`, `SoftDeleteMixin` must exist |
| TASK-003 | Preceding task | `Patient` model must be defined (FK target for `patient_id`) |

---

## Files Modified

| File | Action |
|---|---|
| `backend/app/models/encounter.py` | Create |
| `backend/app/models/__init__.py` | Update (add Encounter exports) |
